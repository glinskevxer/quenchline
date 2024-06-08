from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.instruments.types import (
    Accuracy,
    InstrumentClass,
    InstrumentFunction,
    Readout,
    Span,
    accuracy_at,
    permitted_functions,
    resolution_limit,
)
from quenchline.temperature import Scale, Temperature, TemperatureDelta

SPAN = Span(Temperature.fahrenheit(0), Temperature.fahrenheit(2400))
TENTH = TemperatureDelta(0.1, Scale.FAHRENHEIT)
WHOLE = TemperatureDelta(1.0, Scale.FAHRENHEIT)
COARSE = TemperatureDelta(5.0, Scale.FAHRENHEIT)


def test_function_groups() -> None:
    assert InstrumentFunction.FIELD_TEST.is_test_equipment
    assert not InstrumentFunction.CONTROLLING.is_test_equipment
    assert InstrumentFunction.CONTROLLING.acts_on_the_furnace
    assert InstrumentFunction.OVER_TEMPERATURE.acts_on_the_furnace
    assert not InstrumentFunction.RECORDING.acts_on_the_furnace
    assert not InstrumentFunction.MONITORING.acts_on_the_furnace


def test_readout_resolution() -> None:
    assert Readout.DIGITAL.is_readable_to_a_tenth
    assert not Readout.ANALOGUE.is_readable_to_a_tenth


def test_accuracy_validation() -> None:
    with pytest.raises(ValidationError):
        Accuracy(0.0, InstrumentClass.PERCENT_OF_READING)
    with pytest.raises(ValidationError):
        Accuracy(0.1, InstrumentClass.PERCENT_OF_READING, floor_f=-1.0)


def test_span_must_run_upward() -> None:
    with pytest.raises(ValidationError):
        Span(Temperature.fahrenheit(2400), Temperature.fahrenheit(0))


def test_span_covers() -> None:
    assert SPAN.covers(Temperature.fahrenheit(1550))
    assert not SPAN.covers(Temperature.fahrenheit(2500))
    assert SPAN.width_f == pytest.approx(2400.0)


def test_percent_of_reading_shrinks_at_low_temperature() -> None:
    accuracy = Accuracy(0.1, InstrumentClass.PERCENT_OF_READING)
    assert accuracy_at(accuracy, SPAN, Temperature.fahrenheit(200)).degf == pytest.approx(0.2)
    assert accuracy_at(accuracy, SPAN, Temperature.fahrenheit(2000)).degf == pytest.approx(2.0)


def test_percent_of_span_is_the_same_everywhere() -> None:
    accuracy = Accuracy(0.1, InstrumentClass.PERCENT_OF_SPAN)
    low = accuracy_at(accuracy, SPAN, Temperature.fahrenheit(200))
    high = accuracy_at(accuracy, SPAN, Temperature.fahrenheit(2000))
    assert low.degf == pytest.approx(2.4)
    assert high.degf == pytest.approx(2.4)


def test_the_accuracy_floor_wins_when_the_percentage_is_tiny() -> None:
    accuracy = Accuracy(0.1, InstrumentClass.PERCENT_OF_READING, floor_f=1.0)
    assert accuracy_at(accuracy, SPAN, Temperature.fahrenheit(200)).degf == pytest.approx(1.0)


def test_a_reading_outside_the_span_is_refused() -> None:
    with pytest.raises(ValidationError):
        accuracy_at(
            Accuracy(0.1, InstrumentClass.PERCENT_OF_READING),
            SPAN,
            Temperature.fahrenheit(2500),
        )


def test_field_test_resolution_relaxes_above_a_thousand() -> None:
    assert resolution_limit(
        InstrumentFunction.FIELD_TEST, Temperature.fahrenheit(900)
    ).degf == pytest.approx(0.1)
    assert resolution_limit(
        InstrumentFunction.FIELD_TEST, Temperature.fahrenheit(1550)
    ).degf == pytest.approx(1.0)


def test_the_relaxation_point_is_inclusive() -> None:
    at_limit = resolution_limit(InstrumentFunction.FIELD_TEST, Temperature.fahrenheit(1000))
    just_past = resolution_limit(InstrumentFunction.FIELD_TEST, Temperature.fahrenheit(1000.1))
    assert at_limit.degf == pytest.approx(0.1)
    assert just_past.degf == pytest.approx(1.0)


def test_controlling_and_monitoring_resolution() -> None:
    at = Temperature.fahrenheit(1550)
    assert resolution_limit(InstrumentFunction.CONTROLLING, at).degf == pytest.approx(1.0)
    assert resolution_limit(InstrumentFunction.MONITORING, at).degf == pytest.approx(2.0)


def test_a_good_digital_instrument_qualifies_for_everything() -> None:
    allowed = permitted_functions(
        Accuracy(0.05, InstrumentClass.PERCENT_OF_READING),
        SPAN,
        WHOLE,
        Readout.DIGITAL,
        Temperature.fahrenheit(1550),
    )
    assert allowed == frozenset(InstrumentFunction)


def test_an_analogue_instrument_is_never_field_test_equipment() -> None:
    allowed = permitted_functions(
        Accuracy(0.05, InstrumentClass.PERCENT_OF_READING),
        SPAN,
        WHOLE,
        Readout.ANALOGUE,
        Temperature.fahrenheit(1550),
    )
    assert InstrumentFunction.FIELD_TEST not in allowed
    assert InstrumentFunction.CONTROLLING in allowed


def test_a_coarse_display_drops_the_demanding_jobs_first() -> None:
    allowed = permitted_functions(
        Accuracy(0.05, InstrumentClass.PERCENT_OF_READING),
        SPAN,
        COARSE,
        Readout.DIGITAL,
        Temperature.fahrenheit(1550),
    )
    assert allowed == frozenset()


def test_a_tenth_degree_display_is_needed_low_down() -> None:
    at = Temperature.fahrenheit(600)
    accuracy = Accuracy(0.05, InstrumentClass.PERCENT_OF_READING)
    whole = permitted_functions(accuracy, SPAN, WHOLE, Readout.DIGITAL, at)
    tenth = permitted_functions(accuracy, SPAN, TENTH, Readout.DIGITAL, at)
    assert InstrumentFunction.FIELD_TEST not in whole
    assert InstrumentFunction.FIELD_TEST in tenth


def test_a_loose_instrument_can_still_monitor() -> None:
    allowed = permitted_functions(
        Accuracy(0.3, InstrumentClass.PERCENT_OF_SPAN),
        SPAN,
        WHOLE,
        Readout.DIGITAL,
        Temperature.fahrenheit(1550),
    )
    assert InstrumentFunction.MONITORING in allowed
    assert InstrumentFunction.CONTROLLING not in allowed
    assert InstrumentFunction.FIELD_TEST not in allowed


def test_the_same_instrument_can_change_verdict_with_temperature() -> None:
    accuracy = Accuracy(0.2, InstrumentClass.PERCENT_OF_READING)
    cool = permitted_functions(
        accuracy, SPAN, WHOLE, Readout.DIGITAL, Temperature.fahrenheit(1500)
    )
    hot = permitted_functions(
        accuracy, SPAN, WHOLE, Readout.DIGITAL, Temperature.fahrenheit(2200)
    )
    assert InstrumentFunction.CONTROLLING in cool
    assert InstrumentFunction.CONTROLLING not in hot
