from __future__ import annotations

from datetime import date

import pytest

from quenchline.calendar_rules import DueRule, Interval
from quenchline.errors import ValidationError
from quenchline.identity import InstrumentTag
from quenchline.instruments.calibration import (
    CalibrationCheck,
    CalibrationVerdict,
    InstrumentCalibration,
    error_at,
    suspect_window,
)
from quenchline.temperature import Scale, Temperature, TemperatureDelta

TAG = InstrumentTag.parse("IC-04")
TOLERANCE = TemperatureDelta(2.0, Scale.FAHRENHEIT)
PERFORMED = date(2024, 6, 10)


def check(nominal: float, found: float, left: float | None = None) -> CalibrationCheck:
    return CalibrationCheck(
        Temperature.fahrenheit(nominal),
        Temperature.fahrenheit(found),
        None if left is None else Temperature.fahrenheit(left),
    )


def calibration(
    *checks: CalibrationCheck, number: str = "CAL-2406-01"
) -> InstrumentCalibration:
    return InstrumentCalibration(number, TAG, PERFORMED, checks, TOLERANCE)


def test_errors_are_signed() -> None:
    assert check(1000.0, 1001.5).found_error.degf == pytest.approx(1.5)
    assert check(1000.0, 998.5).found_error.degf == pytest.approx(-1.5)


def test_as_left_error_is_none_when_nothing_was_adjusted() -> None:
    assert check(1000.0, 1001.5).left_error is None
    assert not check(1000.0, 1001.5).was_adjusted


def test_an_adjusted_point_records_both_readings() -> None:
    c = check(1000.0, 1005.0, 1000.2)
    assert c.was_adjusted
    assert c.found_error.degf == pytest.approx(5.0)
    assert c.left_error is not None
    assert c.left_error.degf == pytest.approx(0.2)


def test_a_reading_left_where_it_was_is_not_an_adjustment() -> None:
    assert not check(1000.0, 1001.0, 1001.0).was_adjusted


def test_calibration_validation() -> None:
    with pytest.raises(ValidationError):
        InstrumentCalibration("  ", TAG, PERFORMED, (check(1000.0, 1000.0),), TOLERANCE)
    with pytest.raises(ValidationError):
        InstrumentCalibration("CAL-1", TAG, PERFORMED, (), TOLERANCE)
    with pytest.raises(ValidationError):
        InstrumentCalibration(
            "CAL-1",
            TAG,
            PERFORMED,
            (check(1000.0, 1000.0),),
            TemperatureDelta(0.0, Scale.FAHRENHEIT),
        )


def test_a_clean_calibration_passes() -> None:
    cal = calibration(check(600.0, 600.5), check(1550.0, 1551.0))
    assert cal.as_found_passed()
    assert cal.as_left_passed()
    assert cal.verdict is CalibrationVerdict.PASSED


def test_the_tolerance_boundary_is_inclusive() -> None:
    cal = calibration(check(1550.0, 1552.0))
    assert cal.as_found_passed()
    assert calibration(check(1550.0, 1552.1)).as_found_passed() is False


def test_an_out_of_tolerance_point_brought_back_is_adjusted() -> None:
    cal = calibration(check(600.0, 600.5), check(1550.0, 1556.0, 1550.5))
    assert not cal.as_found_passed()
    assert cal.as_left_passed()
    assert cal.verdict is CalibrationVerdict.ADJUSTED


def test_an_instrument_that_cannot_be_brought_in_fails() -> None:
    cal = calibration(check(1550.0, 1556.0, 1553.0))
    assert cal.verdict is CalibrationVerdict.FAILED
    assert not cal.verdict.is_usable


def test_an_in_tolerance_instrument_that_was_still_tweaked_reads_as_adjusted() -> None:
    cal = calibration(check(1550.0, 1551.0, 1550.1))
    assert cal.as_found_passed()
    assert cal.verdict is CalibrationVerdict.ADJUSTED


def test_verdict_properties() -> None:
    assert CalibrationVerdict.PASSED.is_usable
    assert CalibrationVerdict.ADJUSTED.is_usable
    assert not CalibrationVerdict.FAILED.is_usable
    assert not CalibrationVerdict.PASSED.invalidates_history
    assert CalibrationVerdict.ADJUSTED.invalidates_history
    assert CalibrationVerdict.FAILED.invalidates_history


def test_the_worst_points_are_found() -> None:
    cal = calibration(check(600.0, 600.5), check(1550.0, 1556.0, 1550.5))
    assert cal.worst_found.nominal.degf == pytest.approx(1550.0)
    worst_left = cal.worst_left
    assert worst_left is not None
    assert worst_left.nominal.degf == pytest.approx(1550.0)


def test_worst_left_is_none_when_nothing_was_adjusted() -> None:
    assert calibration(check(600.0, 600.5)).worst_left is None


def test_a_passing_calibration_puts_nothing_in_doubt() -> None:
    cal = calibration(check(1550.0, 1551.0))
    assert suspect_window(cal, None) is None


def test_an_adjusted_calibration_reaches_back_to_the_previous_one() -> None:
    previous = InstrumentCalibration(
        "CAL-2312-01", TAG, date(2023, 12, 1), (check(1550.0, 1550.5),), TOLERANCE
    )
    cal = calibration(check(1550.0, 1556.0, 1550.5))
    window = suspect_window(cal, previous)
    assert window == (date(2023, 12, 1), PERFORMED)


def test_with_no_previous_calibration_the_window_is_a_single_day() -> None:
    cal = calibration(check(1550.0, 1556.0, 1550.5))
    assert suspect_window(cal, None) == (PERFORMED, PERFORMED)


def test_next_due_uses_the_rule_it_is_given() -> None:
    cal = calibration(check(1550.0, 1550.5))
    assert cal.next_due(Interval.months(6)) == date(2024, 12, 10)
    assert cal.next_due(Interval.months(6), DueRule.END_OF_MONTH) == date(2024, 12, 31)


def test_error_at_finds_a_checked_point() -> None:
    cal = calibration(check(600.0, 600.5), check(1550.0, 1551.0))
    found = error_at(cal, Temperature.fahrenheit(600))
    assert found is not None
    assert found.degf == pytest.approx(0.5)
    assert error_at(cal, Temperature.fahrenheit(900)) is None


def test_worst_left_picks_the_largest_adjusted_error() -> None:
    cal = calibration(
        check(600.0, 605.0, 600.2),
        check(1000.0, 1006.0, 1001.5),
        check(1550.0, 1551.0),
    )
    worst = cal.worst_left
    assert worst is not None
    assert worst.nominal.degf == pytest.approx(1000.0)


def test_worst_left_ignores_points_that_were_never_adjusted() -> None:
    cal = calibration(check(600.0, 609.0), check(1000.0, 1006.0, 1001.5))
    worst = cal.worst_left
    assert worst is not None
    assert worst.nominal.degf == pytest.approx(1000.0)
