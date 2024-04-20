from __future__ import annotations

from datetime import date

import pytest

from quenchline.calendar_rules import Interval
from quenchline.errors import OutOfRangeError, ValidationError
from quenchline.sensors.calibration import CalibrationPoint, Certificate, Convention
from quenchline.temperature import Scale, Temperature, TemperatureDelta

ISSUED = date(2024, 1, 18)
READINGS = [(600.0, 1.0), (1000.0, 2.0), (1600.0, -1.0)]


def cert(convention: Convention = Convention.CORRECTION) -> Certificate:
    return Certificate.of("C-2401-118", ISSUED, READINGS, convention=convention)


def test_certificate_holds_its_points() -> None:
    c = cert()
    assert len(c.points) == 3
    assert c.low.degf == pytest.approx(600.0)
    assert c.high.degf == pytest.approx(1600.0)
    assert not c.is_single_point


def test_points_are_sorted_however_they_were_given() -> None:
    c = Certificate.of(
        "C-1", ISSUED, [(1600.0, -1.0), (600.0, 1.0)], convention=Convention.CORRECTION
    )
    assert [p.nominal_f for p in c.sorted_points] == [600.0, 1600.0]


def test_a_blank_number_is_refused() -> None:
    with pytest.raises(ValidationError):
        Certificate.of("  ", ISSUED, READINGS, convention=Convention.CORRECTION)


def test_a_certificate_with_no_points_is_refused() -> None:
    with pytest.raises(ValidationError):
        Certificate.of("C-1", ISSUED, [], convention=Convention.CORRECTION)


def test_two_points_at_the_same_temperature_are_refused() -> None:
    with pytest.raises(ValidationError):
        Certificate.of(
            "C-1", ISSUED, [(600.0, 1.0), (600.0, 2.0)], convention=Convention.CORRECTION
        )


def test_correction_interpolates_between_points() -> None:
    assert cert().correction_at(Temperature.fahrenheit(800)).degf == pytest.approx(1.5)


def test_correction_on_a_calibrated_point_is_exact() -> None:
    assert cert().correction_at(Temperature.fahrenheit(1000)).degf == pytest.approx(2.0)


def test_a_deviation_certificate_flips_the_sign() -> None:
    correction = cert(Convention.CORRECTION).correction_at(Temperature.fahrenheit(1000))
    deviation = cert(Convention.DEVIATION).correction_at(Temperature.fahrenheit(1000))
    assert correction.degf == pytest.approx(2.0)
    assert deviation.degf == pytest.approx(-2.0)


def test_convention_sign() -> None:
    assert Convention.CORRECTION.sign == pytest.approx(1.0)
    assert Convention.DEVIATION.sign == pytest.approx(-1.0)


def test_apply_adds_the_correction_to_the_indicated_reading() -> None:
    true_value = cert().apply(Temperature.fahrenheit(1000))
    assert true_value.degf == pytest.approx(1002.0)


def test_apply_with_a_deviation_certificate_subtracts() -> None:
    true_value = cert(Convention.DEVIATION).apply(Temperature.fahrenheit(1000))
    assert true_value.degf == pytest.approx(998.0)


def test_outside_the_calibrated_range_is_refused() -> None:
    with pytest.raises(OutOfRangeError):
        cert().correction_at(Temperature.fahrenheit(400))
    with pytest.raises(OutOfRangeError):
        cert().correction_at(Temperature.fahrenheit(1800))


def test_covers_matches_the_range() -> None:
    c = cert()
    assert c.covers(Temperature.fahrenheit(600))
    assert c.covers(Temperature.fahrenheit(1600))
    assert not c.covers(Temperature.fahrenheit(1601))


def test_a_single_point_certificate_applies_everywhere() -> None:
    c = Certificate.of("C-2", ISSUED, [(1550.0, 3.0)], convention=Convention.CORRECTION)
    assert c.is_single_point
    assert c.correction_at(Temperature.fahrenheit(200)).degf == pytest.approx(3.0)
    assert c.correction_at(Temperature.fahrenheit(2000)).degf == pytest.approx(3.0)


def test_largest_correction_ignores_sign() -> None:
    assert cert().largest_correction().degf == pytest.approx(2.0)


def test_expiry_uses_the_interval_it_is_given() -> None:
    c = cert()
    assert c.expires(Interval.months(12)) == date(2025, 1, 18)
    assert not c.is_expired(date(2025, 1, 18), Interval.months(12))
    assert c.is_expired(date(2025, 1, 19), Interval.months(12))


def test_points_can_be_built_on_the_celsius_scale() -> None:
    c = Certificate.of(
        "C-3",
        ISSUED,
        [(300.0, 1.0), (900.0, 2.0)],
        convention=Convention.CORRECTION,
        scale=Scale.CELSIUS,
    )
    assert c.low.scale is Scale.CELSIUS
    assert c.correction_at(Temperature.celsius(600)).degf == pytest.approx(2.7)


def test_a_point_reports_its_nominal_in_fahrenheit() -> None:
    point = CalibrationPoint(Temperature.celsius(845), TemperatureDelta(1.0, Scale.CELSIUS))
    assert point.nominal_f == pytest.approx(1553.0)
