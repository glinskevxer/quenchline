from __future__ import annotations

from datetime import date, datetime

import pytest

from quenchline.errors import StateError, ValidationError
from quenchline.hardness.sampling import Specification, judge
from quenchline.hardness.scales import Hardness, HardnessScale
from quenchline.identity import FurnaceTag, LotNumber, WorkOrder
from quenchline.loads.record import Load, LoadState, PartLine
from quenchline.loads.trace import Channel, ChannelRole, Trace
from quenchline.measure import Mass
from quenchline.recipes.cycle import Recipe
from quenchline.recipes.steps import quench, ramp, soak, temper
from quenchline.report.certificate import (
    CertificateHeader,
    certificate_text,
    cycle_table,
    hardness_table,
)
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes

RECIPE = Recipe(
    "HT-4140-Q",
    "C",
    "4140 harden and temper",
    (
        ramp("heat", Temperature.fahrenheit(1550), maximum_per_hour=400.0),
        soak("austenitise", Temperature.fahrenheit(1550), degf(25), minutes(60)),
        quench("oil quench", "AAA fast oil", minutes(0.5)),
        temper("temper", Temperature.fahrenheit(400), degf(15), minutes(120)),
    ),
)

TRACE = Trace(
    datetime(2024, 11, 4, 7, 0),
    (Channel.of("C1", ChannelRole.CONTROL, [(minutes(0), 100.0), (minutes(300), 1550.0)]),),
)

HEADER = CertificateHeader(
    number="CERT-25-0041",
    issued_on=date(2025, 3, 20),
    shop_name="Ravensthorpe Heat Treat",
    customer="Bardsley Gears",
    customer_order="PO-88431",
    specification="AMS 2759/2",
    signatory="D Turnbull",
)

SPEC = Specification(HardnessScale.HRC, minimum=40.0, maximum=45.0)


def load(state: LoadState = LoadState.CERTIFIED, **changes: object) -> Load:
    base: dict[str, object] = {
        "lot": LotNumber.parse("L24-0917"),
        "work_order": WorkOrder.parse("W104417"),
        "furnace": FurnaceTag.parse("HT-04"),
        "recipe_code": "HT-4140-Q",
        "recipe_revision": "C",
        "parts": (PartLine("PN-8891", 40, "4140"),),
        "weight": Mass.pounds(1450),
        "state": state,
        "finished_at": datetime(2024, 11, 4, 12, 0),
        "trace": TRACE,
    }
    base.update(changes)
    return Load(**base)  # type: ignore[arg-type]


def test_header_validation() -> None:
    with pytest.raises(ValidationError):
        CertificateHeader("  ", date(2025, 3, 20), "shop")
    with pytest.raises(ValidationError):
        CertificateHeader("CERT-1", date(2025, 3, 20), " ")


def test_a_certified_load_gets_a_certificate() -> None:
    text = certificate_text(HEADER, load(), RECIPE)
    assert "certificate of conformance" in text
    assert "CERT-25-0041" in text
    assert "Bardsley Gears" in text
    assert "L24-0917" in text
    assert "AMS 2759/2" in text


def test_an_uncertified_load_is_refused() -> None:
    for state in (LoadState.COMPLETE, LoadState.RUNNING, LoadState.REJECTED):
        with pytest.raises(StateError):
            certificate_text(HEADER, load(state), RECIPE)


def test_the_recipe_has_to_be_the_one_the_load_ran() -> None:
    other = Recipe("HT-8620-C", "A", "carburise", RECIPE.steps)
    with pytest.raises(ValidationError):
        certificate_text(HEADER, load(), other)


def test_the_revision_has_to_match_too() -> None:
    with pytest.raises(ValidationError):
        certificate_text(HEADER, load(), RECIPE.revised("D"))


def test_the_cycle_is_printed_on_the_certificate() -> None:
    text = certificate_text(HEADER, load(), RECIPE)
    assert "cycle HT-4140-Q rev C" in text
    assert "austenitise" in text
    assert "AAA fast oil" in text


def test_cycle_table_shows_a_dash_where_a_step_says_nothing() -> None:
    table = cycle_table(RECIPE)
    assert table.rows[0][4] is None
    assert table.rows[2][2] is None


def test_the_parts_are_printed() -> None:
    text = certificate_text(HEADER, load(), RECIPE)
    assert "PN-8891" in text
    assert "4140" in text


def test_hardness_is_left_off_when_none_was_done() -> None:
    text = certificate_text(HEADER, load(), RECIPE)
    assert "hardness" not in text


def test_hardness_is_printed_when_it_was_done() -> None:
    readings = [Hardness(v, HardnessScale.HRC) for v in (41.0, 42.0, 43.0)]
    result = judge(readings, SPEC, 9)
    text = certificate_text(HEADER, load(), RECIPE, (result, SPEC))
    assert "hardness against 40 to 45 HRC" in text
    assert "accepted" in text


def test_a_converted_reading_is_marked_on_the_table() -> None:
    readings = [
        Hardness(41.0, HardnessScale.HRC),
        Hardness(42.0, HardnessScale.HRC, converted=True),
    ]
    spec = Specification(HardnessScale.HRC, minimum=40.0, maximum=45.0, allow_converted=True)
    result = judge(readings, spec, 4)
    table = hardness_table(result, spec)
    assert table.rows[0][2] == "measured"
    assert table.rows[1][2] == "converted"


def test_an_out_of_range_reading_is_marked_out() -> None:
    readings = [Hardness(v, HardnessScale.HRC) for v in (41.0, 42.0, 38.0)]
    result = judge(readings, SPEC, 9)
    table = hardness_table(result, SPEC)
    assert [row[3] for row in table.rows] == ["in", "in", "out"]


def test_the_signature_block_is_last() -> None:
    text = certificate_text(HEADER, load(), RECIPE)
    assert text.strip().endswith("2025-03-20")
    assert "D Turnbull" in text


def test_an_unsigned_certificate_shows_a_dash() -> None:
    header = CertificateHeader("CERT-1", date(2025, 3, 20), "shop")
    text = certificate_text(header, load(), RECIPE)
    assert "signed  -" in text
