from __future__ import annotations

from datetime import date

import pytest

from quenchline.calendar_rules import DueRule, Interval
from quenchline.errors import StateError, ValidationError
from quenchline.identity import InstrumentTag
from quenchline.instruments.calibration import CalibrationCheck, InstrumentCalibration
from quenchline.instruments.record import Instrument, InstrumentStatus
from quenchline.instruments.types import (
    Accuracy,
    InstrumentClass,
    InstrumentFunction,
    Span,
)
from quenchline.temperature import Scale, Temperature, TemperatureDelta

TAG = InstrumentTag.parse("IC-04")
OTHER = InstrumentTag.parse("IC-05")
SPAN = Span(Temperature.fahrenheit(0), Temperature.fahrenheit(2400))
TOLERANCE = TemperatureDelta(2.0, Scale.FAHRENHEIT)
WHOLE = TemperatureDelta(1.0, Scale.FAHRENHEIT)


def cal(
    number: str,
    performed: date,
    found: float,
    left: float | None = None,
    tag: InstrumentTag = TAG,
) -> InstrumentCalibration:
    check = CalibrationCheck(
        Temperature.fahrenheit(1550.0),
        Temperature.fahrenheit(found),
        None if left is None else Temperature.fahrenheit(left),
    )
    return InstrumentCalibration(number, tag, performed, (check,), TOLERANCE)


def instrument(**changes: object) -> Instrument:
    base: dict[str, object] = {
        "tag": TAG,
        "function": InstrumentFunction.CONTROLLING,
        "span": SPAN,
        "accuracy": Accuracy(0.1, InstrumentClass.PERCENT_OF_READING),
        "resolution": WHOLE,
    }
    base.update(changes)
    return Instrument(**base)  # type: ignore[arg-type]


def test_a_new_instrument_has_no_calibration() -> None:
    inst = instrument()
    assert inst.latest is None
    assert inst.due_on() is None
    assert not inst.in_calibration(date(2024, 7, 1))
    assert inst.calibration_state(date(2024, 7, 1)) == "never calibrated"
    assert str(inst) == "IC-04 controlling"


def test_resolution_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        instrument(resolution=TemperatureDelta(0.0, Scale.FAHRENHEIT))


def test_a_calibration_for_another_instrument_is_refused() -> None:
    with pytest.raises(ValidationError):
        instrument(calibrations=(cal("CAL-1", date(2024, 6, 1), 1550.5, tag=OTHER),))
    with pytest.raises(ValidationError):
        instrument().with_calibration(cal("CAL-1", date(2024, 6, 1), 1550.5, tag=OTHER))


def test_the_same_calibration_cannot_be_filed_twice() -> None:
    inst = instrument().with_calibration(cal("CAL-1", date(2024, 6, 1), 1550.5))
    with pytest.raises(ValidationError):
        inst.with_calibration(cal("CAL-1", date(2024, 12, 1), 1550.5))


def test_history_comes_back_in_date_order() -> None:
    inst = instrument()
    inst = inst.with_calibration(cal("CAL-2", date(2024, 6, 1), 1550.5))
    inst = inst.with_calibration(cal("CAL-1", date(2023, 12, 1), 1550.5))
    assert [c.number for c in inst.history] == ["CAL-1", "CAL-2"]
    assert inst.latest is not None
    assert inst.latest.number == "CAL-2"


def test_previous_to_finds_the_one_before() -> None:
    first = cal("CAL-1", date(2023, 12, 1), 1550.5)
    second = cal("CAL-2", date(2024, 6, 1), 1550.5)
    inst = instrument(calibrations=(first, second))
    assert inst.previous_to(second) is first
    assert inst.previous_to(first) is None


def test_due_date_follows_the_interval_and_rule() -> None:
    inst = instrument().with_calibration(cal("CAL-1", date(2024, 6, 10), 1550.5))
    assert inst.due_on() == date(2024, 12, 10)
    monthly = instrument(due_rule=DueRule.END_OF_MONTH).with_calibration(
        cal("CAL-1", date(2024, 6, 10), 1550.5)
    )
    assert monthly.due_on() == date(2024, 12, 31)


def test_a_longer_interval_moves_the_due_date_out() -> None:
    inst = instrument(interval=Interval.years(1)).with_calibration(
        cal("CAL-1", date(2024, 6, 10), 1550.5)
    )
    assert inst.due_on() == date(2025, 6, 10)


def test_in_calibration_on_the_due_date_itself() -> None:
    inst = instrument().with_calibration(cal("CAL-1", date(2024, 6, 10), 1550.5))
    assert inst.in_calibration(date(2024, 12, 10))
    assert not inst.in_calibration(date(2024, 12, 11))


def test_an_adjusted_calibration_still_leaves_it_in_calibration() -> None:
    inst = instrument().with_calibration(cal("CAL-1", date(2024, 6, 10), 1556.0, 1550.2))
    assert inst.in_calibration(date(2024, 7, 1))


def test_a_failed_calibration_takes_it_out_whatever_the_date() -> None:
    inst = instrument().with_calibration(cal("CAL-1", date(2024, 6, 10), 1556.0, 1554.0))
    assert not inst.in_calibration(date(2024, 6, 11))
    assert "failed calibration" in inst.calibration_state(date(2024, 6, 11))


def test_calibration_state_reports_the_overdue_date() -> None:
    inst = instrument().with_calibration(cal("CAL-1", date(2024, 6, 10), 1550.5))
    assert "overdue since 2024-12-10" in inst.calibration_state(date(2025, 1, 1))
    assert "in calibration until 2024-12-10" in inst.calibration_state(date(2024, 7, 1))


def test_qualified_for_ignores_calibration_entirely() -> None:
    inst = instrument()
    at = Temperature.fahrenheit(1550)
    assert inst.qualified_for(InstrumentFunction.CONTROLLING, at)
    assert not inst.in_calibration(date(2024, 7, 1))


def test_a_coarse_instrument_is_not_qualified_to_control() -> None:
    inst = instrument(resolution=TemperatureDelta(5.0, Scale.FAHRENHEIT))
    assert not inst.qualified_for(InstrumentFunction.CONTROLLING, Temperature.fahrenheit(1550))


def test_error_at_uses_the_stated_accuracy() -> None:
    assert instrument().error_at(Temperature.fahrenheit(1550)).degf == pytest.approx(1.55)


def test_service_transitions() -> None:
    inst = instrument()
    out = inst.take_out_of_service("display failed")
    assert out.status is InstrumentStatus.OUT_OF_SERVICE
    assert not out.status.is_usable
    assert out.return_to_service().status is InstrumentStatus.IN_SERVICE


def test_a_reason_is_required_to_take_it_out() -> None:
    with pytest.raises(ValidationError):
        instrument().take_out_of_service("   ")


def test_retirement_is_final() -> None:
    retired = instrument().retire()
    assert retired.status is InstrumentStatus.RETIRED
    with pytest.raises(StateError):
        retired.take_out_of_service("anything")
    with pytest.raises(StateError):
        retired.return_to_service()
