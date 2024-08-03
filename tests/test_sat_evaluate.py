from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.sat.evaluate import (
    SatVerdict,
    evaluate,
    method_allowed,
    sat_tolerance,
    worst_of,
)
from quenchline.sat.model import SatMethod, SatReading, SatTest
from quenchline.temperature import Scale, Temperature, TemperatureDelta

FURNACE = FurnaceTag.parse("HT-04")
PERFORMED = date(2024, 7, 8)
SETPOINT = Temperature.fahrenheit(1550)


def delta(value: float) -> TemperatureDelta:
    return TemperatureDelta(value, Scale.FAHRENHEIT)


def side(indicated: float, tag: str) -> SatReading:
    return SatReading(
        Temperature.fahrenheit(indicated), delta(0.0), delta(0.0), SensorTag.parse(tag)
    )


def sat(system: float, probe: float = 1550.0, **changes: object) -> SatTest:
    base: dict[str, object] = {
        "number": "SAT-2407-04",
        "furnace": FURNACE,
        "performed": PERFORMED,
        "setpoint": SETPOINT,
        "system": side(system, "TC-01"),
        "test": side(probe, "TC-99"),
    }
    base.update(changes)
    return SatTest(**base)  # type: ignore[arg-type]


def test_the_fixed_limit_wins_at_low_temperature() -> None:
    tolerance = sat_tolerance(FurnaceClass.CLASS_3, Temperature.fahrenheit(500))
    assert tolerance.degf == pytest.approx(4.0)


def test_the_percentage_wins_at_high_temperature() -> None:
    tolerance = sat_tolerance(FurnaceClass.CLASS_3, Temperature.fahrenheit(1550))
    assert tolerance.degf == pytest.approx(6.2)


def test_a_precision_furnace_gets_a_tighter_limit() -> None:
    tight = sat_tolerance(FurnaceClass.CLASS_1, SETPOINT)
    loose = sat_tolerance(FurnaceClass.CLASS_6, SETPOINT)
    assert tight.degf == pytest.approx(3.1)
    assert loose.degf == pytest.approx(7.75)


def test_not_applying_corrections_tightens_the_limit() -> None:
    applied = sat_tolerance(FurnaceClass.CLASS_3, SETPOINT, apply_corrections=True)
    raw = sat_tolerance(FurnaceClass.CLASS_3, SETPOINT, apply_corrections=False)
    assert raw.degf < applied.degf
    assert raw.degf == pytest.approx(4.65)


def test_the_probe_method_is_always_allowed() -> None:
    for instrumentation in InstrumentationType:
        assert method_allowed(SatMethod.PROBE, instrumentation)


def test_the_alternate_method_needs_good_instrumentation() -> None:
    assert method_allowed(SatMethod.ALTERNATE, InstrumentationType.A)
    assert method_allowed(SatMethod.ALTERNATE, InstrumentationType.B)
    assert not method_allowed(SatMethod.ALTERNATE, InstrumentationType.C)
    assert not method_allowed(SatMethod.ALTERNATE, InstrumentationType.E)


def test_a_close_test_passes() -> None:
    result = evaluate(sat(1552.0), FurnaceClass.CLASS_3, InstrumentationType.D)
    assert result.is_pass
    assert result.verdict is SatVerdict.PASSED
    assert result.difference.degf == pytest.approx(2.0)
    assert result.margin.degf == pytest.approx(4.2)


def test_a_wide_test_fails() -> None:
    result = evaluate(sat(1560.0), FurnaceClass.CLASS_3, InstrumentationType.D)
    assert not result.is_pass
    assert result.margin.degf < 0


def test_the_boundary_is_inclusive() -> None:
    on_limit = evaluate(sat(1556.2), FurnaceClass.CLASS_3, InstrumentationType.D)
    just_past = evaluate(sat(1556.3), FurnaceClass.CLASS_3, InstrumentationType.D)
    assert on_limit.is_pass
    assert not just_past.is_pass


def test_the_sign_of_the_difference_does_not_change_the_verdict() -> None:
    high = evaluate(sat(1556.0), FurnaceClass.CLASS_3, InstrumentationType.D)
    low = evaluate(sat(1544.0), FurnaceClass.CLASS_3, InstrumentationType.D)
    assert high.is_pass
    assert low.is_pass
    assert high.difference.degf == pytest.approx(-low.difference.degf)


def test_the_same_reading_can_pass_one_furnace_and_fail_another() -> None:
    reading = sat(1554.0)
    assert evaluate(reading, FurnaceClass.CLASS_6, InstrumentationType.D).is_pass
    assert not evaluate(reading, FurnaceClass.CLASS_1, InstrumentationType.D).is_pass


def test_a_test_that_passes_corrected_can_fail_uncorrected() -> None:
    reading = sat(1555.0)
    assert evaluate(reading, FurnaceClass.CLASS_3, InstrumentationType.D).is_pass
    raw = reading.with_corrections(apply_corrections=False)
    assert not evaluate(raw, FurnaceClass.CLASS_3, InstrumentationType.D).is_pass


def test_uncorrected_testing_is_noted_on_the_result() -> None:
    raw = sat(1550.0).with_corrections(apply_corrections=False)
    result = evaluate(raw, FurnaceClass.CLASS_3, InstrumentationType.D)
    assert any("corrections not applied" in note for note in result.notes)


def test_a_near_miss_is_noted() -> None:
    result = evaluate(sat(1556.0), FurnaceClass.CLASS_3, InstrumentationType.D)
    assert result.is_pass
    assert any("tenth of the allowance" in note for note in result.notes)


def test_the_alternate_method_on_a_poor_furnace_is_refused() -> None:
    alternate = sat(
        1550.0,
        method=SatMethod.ALTERNATE,
        test=SatReading(Temperature.fahrenheit(1550.0), delta(0.0), delta(0.0)),
    )
    with pytest.raises(ValidationError):
        evaluate(alternate, FurnaceClass.CLASS_3, InstrumentationType.D)
    assert evaluate(alternate, FurnaceClass.CLASS_3, InstrumentationType.A).is_pass


def test_used_fraction_reports_how_much_of_the_allowance_went() -> None:
    result = evaluate(sat(1553.1), FurnaceClass.CLASS_3, InstrumentationType.D)
    assert result.used_fraction == pytest.approx(0.5)


def test_string_form_reports_both_numbers() -> None:
    result = evaluate(sat(1552.0), FurnaceClass.CLASS_3, InstrumentationType.D)
    assert "SAT-2407-04 passed" in str(result)


def test_worst_of_picks_the_tightest_squeeze() -> None:
    results = [
        evaluate(sat(1551.0), FurnaceClass.CLASS_3, InstrumentationType.D),
        evaluate(sat(1556.0), FurnaceClass.CLASS_3, InstrumentationType.D),
        evaluate(sat(1552.0), FurnaceClass.CLASS_3, InstrumentationType.D),
    ]
    worst = worst_of(results)
    assert worst is not None
    assert worst.difference.degf == pytest.approx(6.0)
    assert worst_of([]) is None
