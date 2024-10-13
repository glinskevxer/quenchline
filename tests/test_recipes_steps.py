from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.recipes.steps import (
    RampLimit,
    Step,
    StepKind,
    hold,
    quench,
    ramp,
    soak,
    temper,
)
from quenchline.temperature import Temperature, degf
from quenchline.timespan import ZERO, minutes

SETPOINT = Temperature.fahrenheit(1550)


def test_step_kind_groups() -> None:
    assert StepKind.RAMP.needs_setpoint
    assert StepKind.SOAK.needs_setpoint
    assert StepKind.TEMPER.needs_setpoint
    assert not StepKind.QUENCH.needs_setpoint
    assert not StepKind.HOLD.needs_setpoint
    assert StepKind.SOAK.is_graded_soak
    assert StepKind.TEMPER.is_graded_soak
    assert not StepKind.RAMP.is_graded_soak
    assert StepKind.SOAK.is_in_furnace
    assert not StepKind.QUENCH.is_in_furnace


def test_ramp_limit_validation() -> None:
    with pytest.raises(ValidationError):
        RampLimit(maximum=0.0)
    with pytest.raises(ValidationError):
        RampLimit(minimum=-1.0)
    with pytest.raises(ValidationError):
        RampLimit(maximum=100.0, minimum=200.0)


def test_an_unlimited_ramp_allows_anything() -> None:
    limit = RampLimit()
    assert limit.is_unlimited
    assert limit.allows(9000.0)


def test_a_ramp_limit_ignores_direction() -> None:
    limit = RampLimit(maximum=300.0)
    assert limit.allows(299.0)
    assert limit.allows(-299.0)
    assert not limit.allows(-301.0)


def test_a_minimum_rate_refuses_a_crawl() -> None:
    limit = RampLimit(minimum=50.0)
    assert not limit.allows(20.0)
    assert limit.allows(50.0)


def test_a_soak_carries_a_band_and_a_time() -> None:
    step = soak("austenitise", SETPOINT, degf(25), minutes(60))
    assert step.grades_temperature
    band = step.band
    assert band is not None
    assert band.upper.degf == pytest.approx(1575.0)
    assert str(step) == "soak austenitise at 1550 F"


def test_a_soak_without_a_band_is_refused() -> None:
    with pytest.raises(ValidationError):
        Step(StepKind.SOAK, "austenitise", setpoint=SETPOINT, minimum_time=minutes(60))


def test_a_soak_without_a_minimum_time_is_refused() -> None:
    with pytest.raises(ValidationError):
        Step(StepKind.SOAK, "austenitise", setpoint=SETPOINT, tolerance=degf(25))
    with pytest.raises(ValidationError):
        Step(
            StepKind.SOAK,
            "austenitise",
            setpoint=SETPOINT,
            tolerance=degf(25),
            minimum_time=ZERO,
        )


def test_a_soak_cannot_carry_a_ramp_rate() -> None:
    with pytest.raises(ValidationError):
        Step(
            StepKind.SOAK,
            "austenitise",
            setpoint=SETPOINT,
            tolerance=degf(25),
            minimum_time=minutes(60),
            ramp=RampLimit(maximum=300.0),
        )


def test_a_ramp_cannot_carry_a_minimum_time() -> None:
    with pytest.raises(ValidationError):
        Step(StepKind.RAMP, "heat", setpoint=SETPOINT, minimum_time=minutes(60))


def test_a_ramp_is_built_from_a_rate() -> None:
    step = ramp("heat", SETPOINT, maximum_per_hour=300.0)
    assert step.rate_limit().maximum == pytest.approx(300.0)
    assert not step.grades_temperature


def test_a_step_with_no_ramp_reports_an_unlimited_one() -> None:
    assert hold("equalise").rate_limit().is_unlimited


def test_a_quench_needs_a_delay_and_a_medium() -> None:
    step = quench("oil quench", "AAA fast oil", minutes(0.5))
    assert step.medium == "AAA fast oil"
    assert step.quench_delay == minutes(0.5)
    assert str(step) == "quench oil quench"
    with pytest.raises(ValidationError):
        Step(StepKind.QUENCH, "oil quench", medium="oil")
    with pytest.raises(ValidationError):
        Step(StepKind.QUENCH, "oil quench", quench_delay=minutes(0.5))


def test_a_quench_cannot_carry_a_setpoint() -> None:
    with pytest.raises(ValidationError):
        Step(
            StepKind.QUENCH,
            "oil quench",
            setpoint=SETPOINT,
            quench_delay=minutes(0.5),
            medium="oil",
        )


def test_only_a_quench_carries_a_transfer_delay() -> None:
    with pytest.raises(ValidationError):
        Step(StepKind.HOLD, "wait", quench_delay=minutes(1))


def test_a_temper_is_a_graded_soak() -> None:
    step = temper("temper", Temperature.fahrenheit(400), degf(15), minutes(120))
    assert step.grades_temperature
    assert step.kind is StepKind.TEMPER


def test_a_hold_grades_nothing() -> None:
    step = hold("equalise", minutes(20))
    assert not step.grades_temperature
    assert step.band is None


def test_a_step_needs_a_name() -> None:
    with pytest.raises(ValidationError):
        hold("   ")


def test_crossed_time_limits_are_refused() -> None:
    with pytest.raises(ValidationError):
        Step(
            StepKind.SOAK,
            "austenitise",
            setpoint=SETPOINT,
            tolerance=degf(25),
            minimum_time=minutes(60),
            maximum_time=minutes(30),
        )
