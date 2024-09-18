from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.sensors.calibration import Certificate, Convention
from quenchline.temperature import Temperature
from quenchline.timespan import minutes
from quenchline.tus.corrections import (
    CorrectionSet,
    MissingPolicy,
    correct_scan,
    correct_setpoint,
    correct_survey,
)
from quenchline.tus.survey import Scan, Survey, SurveyPoint, SurveySetpoint

ISSUED = date(2024, 1, 10)


def certificate(number: str, values: list[tuple[float, float]]) -> Certificate:
    return Certificate.of(number, ISSUED, values, convention=Convention.CORRECTION)


WIDE = certificate("C-1", [(600.0, 1.0), (1800.0, 3.0)])
NARROW = certificate("C-2", [(600.0, 1.0), (900.0, 2.0)])
SINGLE = certificate("C-3", [(1550.0, -2.0)])


def scan(elapsed: float, values: dict[str, float]) -> Scan:
    return Scan.of(minutes(elapsed), {k: Temperature.fahrenheit(v) for k, v in values.items()})


def survey(*keys: str) -> Survey:
    points = tuple(
        SurveyPoint(SensorTag.parse(k.replace("TC-0000", "TC-")), "pos") for k in keys
    )
    readings = SurveySetpoint(
        Temperature.fahrenheit(1550),
        (scan(0, dict.fromkeys(keys, 1540.0)), scan(40, dict.fromkeys(keys, 1550.0))),
    )
    return Survey(
        "TUS-1", FurnaceTag.parse("HT-04"), "main", date(2024, 9, 3), points, (readings,)
    )


def test_missing_policy_flag() -> None:
    assert MissingPolicy.REFUSE.is_strict
    assert not MissingPolicy.LEAVE_RAW.is_strict


def test_a_correction_set_reports_what_it_holds() -> None:
    corrections = CorrectionSet()
    corrections.add("TC-00001", WIDE)
    assert corrections.covers("TC-00001")
    assert corrections.missing_for(("TC-00001", "TC-00002")) == ("TC-00002",)


def test_the_same_sensor_cannot_be_given_two_certificates() -> None:
    corrections = CorrectionSet()
    corrections.add("TC-00001", WIDE)
    with pytest.raises(ValidationError):
        corrections.add("TC-00001", SINGLE)


def test_a_sensor_correction_is_applied() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE})
    corrected = corrections.apply("TC-00001", Temperature.fahrenheit(1200))
    assert corrected.degf == pytest.approx(1202.0)


def test_the_instrument_correction_adds_on_top() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE}, instrument=SINGLE)
    corrected = corrections.apply("TC-00001", Temperature.fahrenheit(1200))
    assert corrected.degf == pytest.approx(1200.0)


def test_a_missing_certificate_is_refused_by_default() -> None:
    corrections = CorrectionSet()
    with pytest.raises(ValidationError):
        corrections.apply("TC-00001", Temperature.fahrenheit(1550))


def test_a_missing_certificate_can_be_left_raw_on_request() -> None:
    corrections = CorrectionSet(policy=MissingPolicy.LEAVE_RAW)
    left = corrections.apply("TC-00001", Temperature.fahrenheit(1550))
    assert left.degf == pytest.approx(1550.0)


def test_a_certificate_that_does_not_reach_the_reading_is_refused() -> None:
    corrections = CorrectionSet({"TC-00001": NARROW})
    with pytest.raises(ValidationError):
        corrections.apply("TC-00001", Temperature.fahrenheit(1550))


def test_an_instrument_certificate_that_falls_short_is_refused() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE}, instrument=NARROW)
    with pytest.raises(ValidationError):
        corrections.apply("TC-00001", Temperature.fahrenheit(1550))


def test_correcting_a_scan_keeps_its_time_and_sensors() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE, "TC-00002": WIDE})
    corrected = correct_scan(scan(10, {"TC-00001": 1200.0, "TC-00002": 1200.0}), corrections)
    assert corrected.elapsed == minutes(10)
    assert corrected.keys == ("TC-00001", "TC-00002")
    assert corrected.get("TC-00001").degf == pytest.approx(1202.0)


def test_correcting_a_setpoint_walks_every_scan() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE})
    data = SurveySetpoint(
        Temperature.fahrenheit(1550),
        (scan(0, {"TC-00001": 1540.0}), scan(40, {"TC-00001": 1550.0})),
    )
    corrected = correct_setpoint(data, corrections)
    assert corrected.setpoint.degf == pytest.approx(1550.0)
    assert corrected.scans[1].get("TC-00001").degf > 1550.0


def test_correcting_a_survey_needs_a_certificate_for_every_sensor() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE})
    with pytest.raises(ValidationError):
        correct_survey(survey("TC-00001", "TC-00002"), corrections)


def test_a_partly_corrected_survey_is_refused_before_any_work_is_done() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE})
    with pytest.raises(ValidationError) as caught:
        correct_survey(survey("TC-00001", "TC-00002"), corrections)
    assert "TC-00002" in str(caught.value)


def test_a_fully_corrected_survey_keeps_its_shape_and_says_so() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE, "TC-00002": WIDE})
    corrected = correct_survey(survey("TC-00001", "TC-00002"), corrections)
    assert corrected.number == "TUS-1"
    assert corrected.sensor_count == 2
    assert "corrections applied" in corrected.notes
    reading = corrected.setpoints[0].scans[1].get("TC-00001")
    assert reading.degf > 1550.0


def test_leaving_sensors_raw_lets_a_partial_set_through() -> None:
    corrections = CorrectionSet({"TC-00001": WIDE}, policy=MissingPolicy.LEAVE_RAW)
    corrected = correct_survey(survey("TC-00001", "TC-00002"), corrections)
    assert corrected.setpoints[0].scans[1].get("TC-00002").degf == pytest.approx(1550.0)
