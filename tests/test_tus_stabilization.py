from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.furnaces.classes import FurnaceClass
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes
from quenchline.tus.stabilization import (
    OvershootPolicy,
    analyse,
    policy_for,
)
from quenchline.tus.survey import Scan, SurveySetpoint

TOLERANCE = degf(15)


def scan(elapsed: float, values: dict[str, float]) -> Scan:
    return Scan.of(minutes(elapsed), {k: Temperature.fahrenheit(v) for k, v in values.items()})


def data(*scans: Scan) -> SurveySetpoint:
    return SurveySetpoint(Temperature.fahrenheit(1550), scans)


def test_precision_furnaces_get_the_strict_policy() -> None:
    assert policy_for(FurnaceClass.CLASS_1) is OvershootPolicy.STRICT
    assert policy_for(FurnaceClass.CLASS_2) is OvershootPolicy.STRICT
    assert policy_for(FurnaceClass.CLASS_5) is OvershootPolicy.TOLERATED
    assert OvershootPolicy.TOLERATED.allows_recovery
    assert not OvershootPolicy.STRICT.allows_recovery


def test_a_survey_that_never_reached_the_band_never_started() -> None:
    result = analyse(data(scan(0, {"A": 1000.0}), scan(30, {"A": 1500.0})), TOLERANCE)
    assert not result.started
    assert result.started_at is None
    assert result.first_sensor is None


def test_the_clock_starts_when_the_first_sensor_arrives() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1400.0, "B": 1300.0}),
            scan(10, {"A": 1536.0, "B": 1450.0}),
            scan(20, {"A": 1550.0, "B": 1545.0}),
        ),
        TOLERANCE,
    )
    assert result.started
    assert result.started_at == minutes(10)
    assert result.first_sensor == "A"


def test_the_bottom_of_the_band_is_inclusive() -> None:
    result = analyse(data(scan(0, {"A": 1535.0})), TOLERANCE)
    assert result.started_at == minutes(0)


def test_a_fast_corner_starts_the_clock_for_everybody() -> None:
    slow = analyse(
        data(
            scan(0, {"A": 1400.0, "B": 1400.0}),
            scan(20, {"A": 1545.0, "B": 1545.0}),
        ),
        TOLERANCE,
    )
    fast = analyse(
        data(
            scan(0, {"A": 1540.0, "B": 1400.0}),
            scan(20, {"A": 1545.0, "B": 1545.0}),
        ),
        TOLERANCE,
    )
    assert slow.started_at == minutes(20)
    assert fast.started_at == minutes(0)
    assert fast.soak_time > slow.soak_time


def test_an_overshoot_before_the_clock_starts_does_not_count() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1000.0, "B": 1400.0}),
            scan(10, {"A": 1540.0, "B": 1545.0}),
        ),
        TOLERANCE,
    )
    assert result.clean


def test_an_overshoot_after_the_clock_starts_is_caught() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1540.0, "B": 1400.0}),
            scan(10, {"A": 1570.0, "B": 1500.0}),
        ),
        TOLERANCE,
    )
    assert not result.clean
    assert len(result.overshoots) == 1
    assert result.overshoots[0].sensor == "A"
    assert result.overshoots[0].excess.degf == pytest.approx(5.0)


def test_the_top_of_the_band_is_inclusive() -> None:
    result = analyse(data(scan(0, {"A": 1565.0})), TOLERANCE)
    assert result.clean


def test_the_strict_policy_never_recovers() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1540.0}),
            scan(1, {"A": 1570.0}),
            scan(2, {"A": 1550.0}),
        ),
        TOLERANCE,
        policy=OvershootPolicy.STRICT,
    )
    assert not result.recovered


def test_the_tolerated_policy_forgives_a_quick_recovery() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1540.0}),
            scan(1, {"A": 1570.0}),
            scan(2, {"A": 1550.0}),
        ),
        TOLERANCE,
        policy=OvershootPolicy.TOLERATED,
    )
    assert not result.clean
    assert result.recovered


def test_the_tolerated_policy_does_not_forgive_a_slow_one() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1540.0}),
            scan(1, {"A": 1570.0}),
            scan(10, {"A": 1550.0}),
        ),
        TOLERANCE,
        policy=OvershootPolicy.TOLERATED,
    )
    assert not result.recovered


def test_an_overshoot_at_the_very_last_scan_cannot_recover() -> None:
    result = analyse(
        data(scan(0, {"A": 1540.0}), scan(10, {"A": 1570.0})),
        TOLERANCE,
        policy=OvershootPolicy.TOLERATED,
    )
    assert not result.recovered


def test_a_second_sensor_still_out_blocks_recovery() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1540.0, "B": 1540.0}),
            scan(1, {"A": 1570.0, "B": 1571.0}),
            scan(2, {"A": 1550.0, "B": 1572.0}),
        ),
        TOLERANCE,
        policy=OvershootPolicy.TOLERATED,
    )
    assert not result.recovered


def test_the_recovery_window_can_be_widened() -> None:
    readings = data(scan(0, {"A": 1540.0}), scan(1, {"A": 1570.0}), scan(10, {"A": 1550.0}))
    tight = analyse(readings, TOLERANCE, policy=OvershootPolicy.TOLERATED)
    wide = analyse(readings, TOLERANCE, policy=OvershootPolicy.TOLERATED, recovery=minutes(15))
    assert not tight.recovered
    assert wide.recovered


def test_soak_time_is_measured_from_the_clock_start() -> None:
    result = analyse(
        data(scan(0, {"A": 1400.0}), scan(10, {"A": 1540.0}), scan(45, {"A": 1550.0})),
        TOLERANCE,
    )
    assert result.soak_time == minutes(35)


def test_a_zero_tolerance_is_refused() -> None:
    with pytest.raises(ValidationError):
        analyse(data(scan(0, {"A": 1550.0})), degf(0))


def test_the_soak_clock_waits_for_the_whole_zone() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1400.0, "B": 1400.0}),
            scan(10, {"A": 1540.0, "B": 1500.0}),
            scan(20, {"A": 1550.0, "B": 1545.0}),
            scan(60, {"A": 1550.0, "B": 1548.0}),
        ),
        TOLERANCE,
    )
    assert result.started_at == minutes(10)
    assert result.all_in_at == minutes(20)
    assert result.soak_time == minutes(50)
    assert result.uniform_soak == minutes(40)


def test_a_zone_that_never_came_together_has_no_uniform_soak() -> None:
    result = analyse(
        data(
            scan(0, {"A": 1540.0, "B": 1400.0}),
            scan(40, {"A": 1550.0, "B": 1450.0}),
        ),
        TOLERANCE,
    )
    assert result.started
    assert not result.all_in
    assert result.uniform_soak == minutes(0)
