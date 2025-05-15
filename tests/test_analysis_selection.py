from __future__ import annotations

import pytest

from quenchline.analysis.selection import Job, Refusal, able_count, assess, choose, rank
from quenchline.errors import ValidationError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.furnaces.record import Furnace, FurnaceStatus
from quenchline.furnaces.zones import QualifiedRange, WorkZone
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.measure import Volume
from quenchline.sensors.record import SensorRole
from quenchline.temperature import Temperature, degf

WIDE_ZONE = WorkZone(
    "main", Volume(40.0), Temperature.fahrenheit(1000), Temperature.fahrenheit(1800)
)
SMALL_ZONE = WorkZone(
    "small", Volume(4.0), Temperature.fahrenheit(1000), Temperature.fahrenheit(1800)
)
RANGE = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1700))
WIRED = (
    (SensorRole.CONTROL, SensorTag.parse("TC-01")),
    (SensorRole.RECORD, SensorTag.parse("TC-02")),
)
JOB = Job(Temperature.fahrenheit(1550), degf(25))


def furnace(tag: str, **changes: object) -> Furnace:
    base: dict[str, object] = {
        "tag": FurnaceTag.parse(tag),
        "furnace_class": FurnaceClass.CLASS_3,
        "instrumentation": InstrumentationType.D,
        "zones": (WIDE_ZONE,),
        "qualified": RANGE,
        "sensors": WIRED,
    }
    base.update(changes)
    return Furnace(**base)  # type: ignore[arg-type]


def test_a_job_needs_a_positive_band() -> None:
    with pytest.raises(ValidationError):
        Job(Temperature.fahrenheit(1550), degf(0))


def test_a_good_furnace_is_able() -> None:
    candidate = assess(furnace("HT-04"), JOB)
    assert candidate.is_able
    assert candidate.refusals == ()
    assert "fits with" in str(candidate)


def test_a_furnace_that_is_down_is_refused() -> None:
    candidate = assess(furnace("HT-04", status=FurnaceStatus.DOWN), JOB)
    assert Refusal.OUT_OF_SERVICE in candidate.refusals
    assert "refused" in str(candidate)


def test_an_unqualified_furnace_is_refused() -> None:
    candidate = assess(furnace("HT-04", qualified=None), JOB)
    assert Refusal.NOT_QUALIFIED in candidate.refusals


def test_a_furnace_qualified_short_of_the_job_is_refused() -> None:
    narrow = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1400))
    candidate = assess(furnace("HT-04", qualified=narrow), JOB)
    assert Refusal.NOT_QUALIFIED in candidate.refusals


def test_a_zone_that_does_not_reach_the_temperature_is_refused() -> None:
    cool = WorkZone(
        "main", Volume(40.0), Temperature.fahrenheit(600), Temperature.fahrenheit(1200)
    )
    candidate = assess(furnace("HT-04", zones=(cool,)), JOB)
    assert Refusal.NO_ZONE_AT_TEMPERATURE in candidate.refusals


def test_a_band_wider_than_the_job_needs_is_refused() -> None:
    candidate = assess(furnace("HT-04", furnace_class=FurnaceClass.CLASS_6), JOB)
    assert Refusal.BAND_TOO_WIDE in candidate.refusals


def test_a_furnace_missing_its_instrumentation_is_refused() -> None:
    candidate = assess(furnace("HT-04", instrumentation=InstrumentationType.A), JOB)
    assert Refusal.INSTRUMENTATION_SHORT in candidate.refusals


def test_a_zone_too_small_for_the_load_is_refused() -> None:
    job = Job(Temperature.fahrenheit(1550), degf(25), Volume(20.0))
    candidate = assess(furnace("HT-04", zones=(SMALL_ZONE,)), job)
    assert Refusal.ZONE_TOO_SMALL in candidate.refusals


def test_a_big_enough_zone_reports_the_spare_room() -> None:
    job = Job(Temperature.fahrenheit(1550), degf(25), Volume(20.0))
    candidate = assess(furnace("HT-04"), job)
    assert candidate.is_able
    assert candidate.spare_volume == pytest.approx(20.0)


def test_volume_is_only_checked_when_the_job_states_one() -> None:
    assert assess(furnace("HT-04", zones=(SMALL_ZONE,)), JOB).is_able


def test_slack_is_how_much_band_is_left_over() -> None:
    tight = assess(furnace("HT-04", furnace_class=FurnaceClass.CLASS_1), JOB)
    loose = assess(furnace("HT-05", furnace_class=FurnaceClass.CLASS_5), JOB)
    assert tight.slack == pytest.approx(0.8)
    assert loose.slack == pytest.approx(0.0)


def test_the_snuggest_fit_is_ranked_first() -> None:
    ranked = rank(
        [
            furnace("HT-04", furnace_class=FurnaceClass.CLASS_1),
            furnace("HT-05", furnace_class=FurnaceClass.CLASS_5),
            furnace("HT-06", furnace_class=FurnaceClass.CLASS_3),
        ],
        JOB,
    )
    assert [c.tag for c in ranked] == ["HT-05", "HT-06", "HT-04"]


def test_refusals_sort_below_every_able_furnace() -> None:
    ranked = rank(
        [
            furnace("HT-04", furnace_class=FurnaceClass.CLASS_6),
            furnace("HT-05", furnace_class=FurnaceClass.CLASS_1),
        ],
        JOB,
    )
    assert ranked[0].tag == "HT-05"
    assert not ranked[1].is_able


def test_choose_takes_the_loosest_furnace_that_still_holds_the_band() -> None:
    chosen = choose(
        [
            furnace("HT-04", furnace_class=FurnaceClass.CLASS_1),
            furnace("HT-05", furnace_class=FurnaceClass.CLASS_3),
        ],
        JOB,
    )
    assert chosen.tag == "HT-05"


def test_choose_raises_when_nothing_fits() -> None:
    with pytest.raises(ValidationError):
        choose([furnace("HT-04", furnace_class=FurnaceClass.CLASS_6)], JOB)


def test_choose_raises_on_an_empty_shop() -> None:
    with pytest.raises(ValidationError):
        choose([], JOB)


def test_able_count() -> None:
    furnaces = [
        furnace("HT-04"),
        furnace("HT-05", status=FurnaceStatus.DOWN),
        furnace("HT-06", furnace_class=FurnaceClass.CLASS_6),
    ]
    assert able_count(furnaces, JOB) == 1


def test_every_reason_is_reported_not_just_the_first() -> None:
    candidate = assess(
        furnace(
            "HT-04",
            status=FurnaceStatus.DOWN,
            qualified=None,
            furnace_class=FurnaceClass.CLASS_6,
        ),
        JOB,
    )
    assert len(candidate.refusals) >= 3
