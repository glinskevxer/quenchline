from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import NotFoundError, ValidationError
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.temperature import Temperature
from quenchline.timespan import minutes
from quenchline.tus.survey import Scan, Survey, SurveyPoint, SurveySetpoint

FURNACE = FurnaceTag.parse("HT-04")
PERFORMED = date(2024, 9, 3)


def point(
    serial: int, location: str, corner: bool = False, centre: bool = False
) -> SurveyPoint:
    return SurveyPoint(SensorTag.parse(f"TC-{serial}"), location, corner, centre)


def scan(elapsed_minutes: float, values: dict[str, float]) -> Scan:
    return Scan.of(
        minutes(elapsed_minutes),
        {key: Temperature.fahrenheit(value) for key, value in values.items()},
    )


POINTS = (
    point(1, "front top left", corner=True),
    point(2, "front top right", corner=True),
    point(3, "centre", centre=True),
)


def setpoint(temperature: float = 1550.0) -> SurveySetpoint:
    return SurveySetpoint(
        Temperature.fahrenheit(temperature),
        (
            scan(0, {"TC-00001": 1500.0, "TC-00002": 1505.0, "TC-00003": 1510.0}),
            scan(30, {"TC-00001": 1548.0, "TC-00002": 1552.0, "TC-00003": 1550.0}),
        ),
    )


def survey(**changes: object) -> Survey:
    base: dict[str, object] = {
        "number": "TUS-2409-04",
        "furnace": FURNACE,
        "zone": "main",
        "performed": PERFORMED,
        "points": POINTS,
        "setpoints": (setpoint(),),
    }
    base.update(changes)
    return Survey(**base)  # type: ignore[arg-type]


def test_a_point_needs_a_location() -> None:
    with pytest.raises(ValidationError):
        SurveyPoint(SensorTag.parse("TC-01"), "  ")


def test_a_point_cannot_be_a_corner_and_the_centre() -> None:
    with pytest.raises(ValidationError):
        SurveyPoint(SensorTag.parse("TC-01"), "middle", is_corner=True, is_centre=True)


def test_point_key_and_text() -> None:
    p = point(1, "front top left", corner=True)
    assert p.key == "TC-00001"
    assert str(p) == "TC-00001 at front top left"


def test_scan_sorts_its_readings_and_reads_back() -> None:
    s = scan(0, {"TC-00002": 1505.0, "TC-00001": 1500.0})
    assert s.keys == ("TC-00001", "TC-00002")
    assert s.get("TC-00001").degf == pytest.approx(1500.0)
    assert s.has("TC-00002")
    assert not s.has("TC-00099")
    assert not s.is_empty


def test_an_unknown_sensor_in_a_scan_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        scan(0, {"TC-00001": 1500.0}).get("TC-00099")


def test_scan_helpers() -> None:
    s = scan(0, {"TC-00001": 1500.0, "TC-00002": 1505.0})
    assert [t.degf for t in s.temperatures()] == [1500.0, 1505.0]
    assert s.as_mapping()["TC-00002"].degf == pytest.approx(1505.0)
    kept = s.restricted_to({"TC-00002"})
    assert kept.keys == ("TC-00002",)
    assert kept.elapsed == s.elapsed


def test_a_setpoint_needs_scans_in_time_order() -> None:
    with pytest.raises(ValidationError):
        SurveySetpoint(Temperature.fahrenheit(1550), ())
    with pytest.raises(ValidationError):
        SurveySetpoint(
            Temperature.fahrenheit(1550),
            (scan(30, {"TC-00001": 1550.0}), scan(0, {"TC-00001": 1500.0})),
        )


def test_setpoint_reports_its_span_and_sensors() -> None:
    s = setpoint()
    assert s.duration == minutes(30)
    assert s.sensor_keys == ("TC-00001", "TC-00002", "TC-00003")


def test_scans_after_filters_on_elapsed_time() -> None:
    s = setpoint()
    assert len(s.scans_after(minutes(0))) == 2
    assert len(s.scans_after(minutes(1))) == 1
    assert len(s.scans_after(minutes(31))) == 0


def test_series_pulls_one_sensor_out() -> None:
    series = setpoint().series("TC-00001")
    assert [t.degf for _, t in series] == [1500.0, 1548.0]
    assert series[1][0] == minutes(30)


def test_series_of_a_missing_sensor_is_empty() -> None:
    assert setpoint().series("TC-00099") == []


def test_survey_validation() -> None:
    with pytest.raises(ValidationError):
        survey(number="  ")
    with pytest.raises(ValidationError):
        survey(points=())
    with pytest.raises(ValidationError):
        survey(setpoints=())
    with pytest.raises(ValidationError):
        survey(points=(point(1, "a"), point(1, "b")))


def test_survey_counts_its_geometry() -> None:
    s = survey()
    assert s.sensor_count == 3
    assert s.corner_count == 2
    assert s.has_centre
    assert s.keys == ("TC-00001", "TC-00002", "TC-00003")


def test_point_lookup() -> None:
    assert survey().point("TC-00003").is_centre
    with pytest.raises(NotFoundError):
        survey().point("TC-00099")


def test_setpoint_lookup() -> None:
    s = survey(setpoints=(setpoint(1200.0), setpoint(1700.0)))
    assert s.at(Temperature.fahrenheit(1700)).setpoint.degf == pytest.approx(1700.0)
    assert [t.degf for t in s.temperatures] == [1200.0, 1700.0]
    with pytest.raises(NotFoundError):
        s.at(Temperature.fahrenheit(1550))


def test_survey_text() -> None:
    assert str(survey()) == "TUS-2409-04 on HT-04 zone main"
