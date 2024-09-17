from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.furnaces.classes import FurnaceClass
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes
from quenchline.tus.evaluate import FailureReason, evaluate, evaluate_setpoint
from quenchline.tus.stabilization import OvershootPolicy
from quenchline.tus.survey import Scan, Survey, SurveyPoint, SurveySetpoint

TOLERANCE = degf(15)


def scan(elapsed: float, values: dict[str, float]) -> Scan:
    return Scan.of(minutes(elapsed), {k: Temperature.fahrenheit(v) for k, v in values.items()})


def data(*scans: Scan, setpoint: float = 1550.0) -> SurveySetpoint:
    return SurveySetpoint(Temperature.fahrenheit(setpoint), scans)


def good_soak(setpoint: float = 1550.0) -> SurveySetpoint:
    return data(
        scan(0, {"A": setpoint - 150, "B": setpoint - 150}),
        scan(10, {"A": setpoint - 12, "B": setpoint - 14}),
        scan(20, {"A": setpoint - 4, "B": setpoint - 8}),
        scan(50, {"A": setpoint + 2, "B": setpoint - 3}),
        setpoint=setpoint,
    )


def test_a_clean_soak_passes() -> None:
    result = evaluate_setpoint(good_soak(), TOLERANCE)
    assert result.is_pass
    assert result.reasons == ()
    assert result.soak_time == minutes(40)


def test_the_worst_deviations_are_reported_both_ways() -> None:
    result = evaluate_setpoint(good_soak(), TOLERANCE)
    assert result.worst_high.degf == pytest.approx(2.0)
    assert result.worst_low.degf == pytest.approx(-14.0)


def test_the_widest_spread_is_across_one_scan() -> None:
    result = evaluate_setpoint(good_soak(), TOLERANCE)
    assert result.widest_spread.degf == pytest.approx(5.0)


def test_a_furnace_that_never_reached_the_band_fails() -> None:
    result = evaluate_setpoint(data(scan(0, {"A": 1000.0}), scan(40, {"A": 1200.0})), TOLERANCE)
    assert not result.is_pass
    assert FailureReason.NEVER_STABILISED in result.reasons


def test_a_short_soak_fails() -> None:
    result = evaluate_setpoint(data(scan(0, {"A": 1540.0}), scan(10, {"A": 1550.0})), TOLERANCE)
    assert FailureReason.SHORT_SOAK in result.reasons


def test_the_minimum_soak_can_be_shortened() -> None:
    readings = data(scan(0, {"A": 1540.0}), scan(10, {"A": 1550.0}))
    assert evaluate_setpoint(readings, TOLERANCE, minimum_soak=minutes(5)).is_pass


def test_a_sensor_low_during_the_soak_fails_out_of_band() -> None:
    result = evaluate_setpoint(
        data(
            scan(0, {"A": 1540.0, "B": 1540.0}),
            scan(20, {"A": 1550.0, "B": 1520.0}),
            scan(40, {"A": 1550.0, "B": 1548.0}),
        ),
        TOLERANCE,
    )
    assert not result.is_pass
    assert FailureReason.OUT_OF_BAND in result.reasons
    assert result.excursions[0].sensor == "B"


def test_an_overshoot_fails_as_an_overshoot_and_not_as_out_of_band() -> None:
    result = evaluate_setpoint(data(scan(0, {"A": 1540.0}), scan(40, {"A": 1580.0})), TOLERANCE)
    assert FailureReason.OVERSHOOT in result.reasons
    assert FailureReason.OUT_OF_BAND not in result.reasons


def test_an_overshoot_that_recovers_under_a_tolerant_policy_passes() -> None:
    result = evaluate_setpoint(
        data(
            scan(0, {"A": 1540.0}),
            scan(1, {"A": 1580.0}),
            scan(2, {"A": 1550.0}),
            scan(40, {"A": 1550.0}),
        ),
        TOLERANCE,
        policy=OvershootPolicy.TOLERATED,
    )
    assert result.is_pass


def test_a_recovered_overshoot_still_fails_a_strict_furnace() -> None:
    result = evaluate_setpoint(
        data(
            scan(0, {"A": 1540.0}),
            scan(1, {"A": 1580.0}),
            scan(2, {"A": 1550.0}),
            scan(40, {"A": 1550.0}),
        ),
        TOLERANCE,
        policy=OvershootPolicy.STRICT,
    )
    assert not result.is_pass


def test_too_few_sensors_fails_on_its_own() -> None:
    result = evaluate_setpoint(good_soak(), TOLERANCE, required_sensors=9)
    assert FailureReason.TOO_FEW_SENSORS in result.reasons


def test_an_average_on_setpoint_does_not_rescue_a_split_furnace() -> None:
    result = evaluate_setpoint(
        data(
            scan(0, {"A": 1540.0, "B": 1540.0}),
            scan(40, {"A": 1530.0, "B": 1570.0}),
        ),
        TOLERANCE,
    )
    assert not result.is_pass


def test_setpoint_result_text() -> None:
    assert "1550 F passed" in str(evaluate_setpoint(good_soak(), TOLERANCE))


def survey(*setpoints: SurveySetpoint) -> Survey:
    return Survey(
        "TUS-2409-04",
        FurnaceTag.parse("HT-04"),
        "main",
        date(2024, 9, 3),
        (SurveyPoint(SensorTag.parse("TC-01"), "corner", is_corner=True),),
        setpoints,
    )


def test_a_survey_passes_only_when_every_setpoint_passes() -> None:
    result = evaluate(survey(good_soak(1200.0), good_soak(1700.0)), FurnaceClass.CLASS_3)
    assert result.is_pass
    assert result.failed_setpoints == ()


def test_one_bad_setpoint_fails_the_survey() -> None:
    bad = data(scan(0, {"A": 1000.0}), scan(40, {"A": 1100.0}), setpoint=1200.0)
    result = evaluate(survey(bad, good_soak(1700.0)), FurnaceClass.CLASS_3)
    assert not result.is_pass
    assert len(result.failed_setpoints) == 1


def test_the_class_decides_the_band() -> None:
    readings = data(
        scan(0, {"A": 1540.0, "B": 1540.0}),
        scan(40, {"A": 1566.0, "B": 1542.0}),
    )
    assert evaluate(survey(readings), FurnaceClass.CLASS_5).is_pass
    assert not evaluate(survey(readings), FurnaceClass.CLASS_2).is_pass


def test_setpoint_lookup_on_a_result() -> None:
    result = evaluate(survey(good_soak(1200.0), good_soak(1700.0)), FurnaceClass.CLASS_3)
    assert result.at(Temperature.fahrenheit(1700)).setpoint.degf == pytest.approx(1700.0)
    with pytest.raises(ValidationError):
        result.at(Temperature.fahrenheit(1550))


def test_a_zone_that_never_came_together_fails_as_never_stabilised() -> None:
    result = evaluate_setpoint(
        data(
            scan(0, {"A": 1540.0, "B": 1400.0}),
            scan(40, {"A": 1550.0, "B": 1450.0}),
        ),
        TOLERANCE,
    )
    assert not result.is_pass
    assert FailureReason.NEVER_STABILISED in result.reasons


def test_the_soak_is_measured_from_the_last_sensor_in() -> None:
    result = evaluate_setpoint(
        data(
            scan(0, {"A": 1540.0, "B": 1400.0}),
            scan(20, {"A": 1550.0, "B": 1545.0}),
            scan(60, {"A": 1550.0, "B": 1548.0}),
        ),
        TOLERANCE,
    )
    assert result.soak_time == minutes(40)
    assert result.is_pass
