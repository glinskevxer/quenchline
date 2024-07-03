from __future__ import annotations

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.furnaces.record import Deficiency, Furnace, FurnaceStatus
from quenchline.furnaces.register import build_register
from quenchline.furnaces.reporting import (
    capability_summary,
    deficiency_table,
    furnace_table,
)
from quenchline.furnaces.zones import QualifiedRange, WorkZone
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.measure import Volume
from quenchline.sensors.record import SensorRole
from quenchline.temperature import Temperature

MAIN = WorkZone(
    "main", Volume(40.0), Temperature.fahrenheit(1000), Temperature.fahrenheit(1800)
)
RANGE = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1700))
WORKING = Temperature.fahrenheit(1550)


def furnace(tag: str, **changes: object) -> Furnace:
    base: dict[str, object] = {
        "tag": FurnaceTag.parse(tag),
        "furnace_class": FurnaceClass.CLASS_3,
        "instrumentation": InstrumentationType.D,
        "zones": (MAIN,),
        "qualified": RANGE,
        "sensors": (
            (SensorRole.CONTROL, SensorTag.parse("TC-01")),
            (SensorRole.RECORD, SensorTag.parse("TC-02")),
        ),
    }
    base.update(changes)
    return Furnace(**base)  # type: ignore[arg-type]


def test_add_get_and_conflict() -> None:
    register = build_register([furnace("HT-04")])
    assert len(register) == 1
    assert "HT-04" in register
    with pytest.raises(ConflictError):
        register.add(furnace("HT-04"))
    with pytest.raises(NotFoundError):
        register.get("HT-99")
    with pytest.raises(NotFoundError):
        register.replace(furnace("HT-99"))


def test_replace_swaps_the_record() -> None:
    register = build_register([furnace("HT-04")])
    register.replace(furnace("HT-04", description="rebuilt"))
    assert register.get("HT-04").description == "rebuilt"


def test_listing_helpers() -> None:
    register = build_register(
        [
            furnace("HT-11", furnace_class=FurnaceClass.CLASS_1),
            furnace("HT-04", status=FurnaceStatus.DOWN),
        ]
    )
    assert [str(f.tag) for f in register.all()] == ["HT-04", "HT-11"]
    assert [str(f.tag) for f in register.in_service()] == ["HT-11"]
    assert [str(f.tag) for f in register.of_class(FurnaceClass.CLASS_1)] == ["HT-11"]
    assert len(register.with_instrumentation(InstrumentationType.D)) == 2


def test_able_to_run_filters_on_everything_at_once() -> None:
    register = build_register(
        [
            furnace("HT-04"),
            furnace("HT-05", status=FurnaceStatus.DOWN),
            furnace("HT-06", qualified=None),
        ]
    )
    assert [str(f.tag) for f in register.able_to_run(WORKING)] == ["HT-04"]


def test_deficient_lists_the_furnaces_that_do_not_match_their_type() -> None:
    register = build_register(
        [furnace("HT-04"), furnace("HT-05", instrumentation=InstrumentationType.A)]
    )
    deficient = register.deficient()
    assert len(deficient) == 1
    assert str(deficient[0][0].tag) == "HT-05"
    assert Deficiency.NO_OVER_TEMPERATURE in deficient[0][1]


def test_find_sensor_locates_a_wired_couple() -> None:
    register = build_register([furnace("HT-04")])
    found = register.find_sensor("TC-00001")
    assert found is not None
    assert str(found.tag) == "HT-04"
    assert register.find_sensor("TC-00099") is None


def test_tightest_tolerance() -> None:
    register = build_register(
        [furnace("HT-04"), furnace("HT-11", furnace_class=FurnaceClass.CLASS_1)]
    )
    tightest = register.tightest_tolerance()
    assert tightest is not None
    assert str(tightest.tag) == "HT-11"


def test_tightest_tolerance_of_an_empty_register() -> None:
    assert build_register([]).tightest_tolerance() is None


def test_furnace_table_renders_a_row_each() -> None:
    register = build_register([furnace("HT-04"), furnace("HT-11")])
    rendered = furnace_table(register).render()
    assert "furnace register" in rendered
    assert "HT-04" in rendered
    assert "1200 F to 1700 F" in rendered


def test_furnace_table_shows_a_dash_when_unqualified() -> None:
    table = furnace_table(build_register([furnace("HT-04", qualified=None)]))
    assert table.rows[0][5] is None


def test_deficiency_table_only_lists_the_bad_ones() -> None:
    register = build_register(
        [furnace("HT-04"), furnace("HT-05", instrumentation=InstrumentationType.A)]
    )
    table = deficiency_table(register)
    assert len(table.rows) == 1
    assert "no_over_temperature" in str(table.rows[0][2])


def test_capability_summary_counts_what_can_run() -> None:
    register = build_register([furnace("HT-04"), furnace("HT-05", status=FurnaceStatus.DOWN)])
    summary = capability_summary(register, WORKING)
    assert "furnace capability" in summary
    assert "able to run    1" in summary
    assert "in service     1" in summary


def test_capability_summary_of_an_empty_register() -> None:
    summary = capability_summary(build_register([]), WORKING)
    assert "tightest band  -" in summary
