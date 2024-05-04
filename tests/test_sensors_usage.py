from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.sensors.record import Construction, SensorRole
from quenchline.sensors.types import ThermocoupleType
from quenchline.sensors.usage import (
    UsageEvent,
    UsageLedger,
    UsageLimit,
    assess,
    limit_for,
)
from quenchline.temperature import Temperature
from quenchline.timespan import ZERO, hours, minutes


def event(peak_f: float, hrs: float = 2.0, role: SensorRole = SensorRole.LOAD) -> UsageEvent:
    return UsageEvent(date(2024, 5, 1), Temperature.fahrenheit(peak_f), hours(hrs), role)


def test_an_event_needs_a_time_at_temperature() -> None:
    with pytest.raises(ValidationError):
        UsageEvent(date(2024, 5, 1), Temperature.fahrenheit(1550), ZERO, SensorRole.LOAD)


def test_an_empty_ledger_reports_nothing() -> None:
    ledger = UsageLedger()
    assert ledger.is_empty
    assert ledger.uses == 0
    assert ledger.hottest() is None
    assert ledger.last_used() is None
    assert ledger.hours_above(Temperature.fahrenheit(1000)) == pytest.approx(0.0)


def test_ledger_counts_uses_and_finds_the_peak() -> None:
    ledger = UsageLedger()
    ledger.record(event(900.0))
    ledger.record(event(1250.0))
    ledger.record(event(1100.0))
    assert ledger.uses == 3
    assert ledger.hottest() is not None
    assert ledger.hottest().degf == pytest.approx(1250.0)  # type: ignore[union-attr]


def test_hours_above_only_counts_runs_that_reached_the_threshold() -> None:
    ledger = UsageLedger()
    ledger.record(event(900.0, 5.0))
    ledger.record(event(1250.0, 3.0))
    assert ledger.hours_above(Temperature.fahrenheit(1000)) == pytest.approx(3.0)
    assert ledger.hours_above(Temperature.fahrenheit(800)) == pytest.approx(8.0)


def test_ledger_tracks_the_last_use_and_role_counts() -> None:
    ledger = UsageLedger()
    ledger.record(
        UsageEvent(date(2024, 5, 1), Temperature.fahrenheit(900), hours(1), SensorRole.LOAD)
    )
    ledger.record(
        UsageEvent(date(2024, 6, 9), Temperature.fahrenheit(900), hours(1), SensorRole.SURVEY)
    )
    assert ledger.last_used() == date(2024, 6, 9)
    assert ledger.uses_in_role(SensorRole.LOAD) == 1
    assert ledger.uses_in_role(SensorRole.TEST) == 0


def test_limit_validation() -> None:
    with pytest.raises(ValidationError):
        UsageLimit(0, None, Temperature.fahrenheit(1200))
    with pytest.raises(ValidationError):
        UsageLimit(None, 0.0, Temperature.fahrenheit(1200))


def test_a_cool_expendable_couple_gets_three_uses() -> None:
    limit = limit_for(
        ThermocoupleType.K,
        Construction.EXPENDABLE,
        SensorRole.LOAD,
        Temperature.fahrenheit(1100),
    )
    assert limit.max_uses == 3


def test_one_hot_run_puts_an_expendable_couple_on_the_single_use_limit() -> None:
    limit = limit_for(
        ThermocoupleType.K,
        Construction.EXPENDABLE,
        SensorRole.LOAD,
        Temperature.fahrenheit(1250),
    )
    assert limit.max_uses == 1


def test_the_hot_limit_is_decided_by_the_hottest_run_not_the_latest() -> None:
    ledger = UsageLedger()
    ledger.record(event(1250.0))
    ledger.record(event(900.0))
    result = assess(ThermocoupleType.K, Construction.EXPENDABLE, SensorRole.LOAD, ledger)
    assert result.limit.max_uses == 1
    assert result.is_spent


def test_a_brand_new_expendable_couple_gets_the_cool_limit() -> None:
    limit = limit_for(ThermocoupleType.K, Construction.EXPENDABLE, SensorRole.LOAD, None)
    assert limit.max_uses == 3


def test_the_boundary_temperature_itself_is_not_hot() -> None:
    cool = limit_for(
        ThermocoupleType.K,
        Construction.EXPENDABLE,
        SensorRole.LOAD,
        Temperature.fahrenheit(1200),
    )
    hot = limit_for(
        ThermocoupleType.K,
        Construction.EXPENDABLE,
        SensorRole.LOAD,
        Temperature.fahrenheit(1200.1),
    )
    assert cool.max_uses == 3
    assert hot.max_uses == 1


def test_noble_couples_are_not_counted_by_use() -> None:
    limit = limit_for(
        ThermocoupleType.S,
        Construction.NONEXPENDABLE,
        SensorRole.SURVEY,
        Temperature.fahrenheit(2200),
    )
    assert limit.max_uses is None
    assert limit.max_hours == pytest.approx(200.0)
    assert limit.hours_threshold.degf == pytest.approx(2000.0)


def test_a_permanent_base_metal_couple_has_no_limit_at_all() -> None:
    limit = limit_for(ThermocoupleType.N, Construction.NONEXPENDABLE, SensorRole.CONTROL, None)
    assert limit.is_unlimited


def test_a_test_couple_is_governed_by_hours() -> None:
    limit = limit_for(ThermocoupleType.N, Construction.NONEXPENDABLE, SensorRole.TEST, None)
    assert limit.max_hours == pytest.approx(1000.0)


def test_assessment_of_an_unused_couple() -> None:
    result = assess(ThermocoupleType.K, Construction.EXPENDABLE, SensorRole.LOAD, UsageLedger())
    assert not result.is_spent
    assert result.uses_remaining == 3
    assert "3 use(s) left" in result.reason


def test_assessment_of_an_unlimited_couple_says_so() -> None:
    result = assess(
        ThermocoupleType.N, Construction.NONEXPENDABLE, SensorRole.CONTROL, UsageLedger()
    )
    assert not result.is_spent
    assert result.uses_remaining is None
    assert "system accuracy" in result.reason


def test_a_couple_is_spent_when_the_hours_run_out() -> None:
    ledger = UsageLedger()
    for _ in range(70):
        ledger.record(event(2200.0, 3.0, SensorRole.SURVEY))
    result = assess(ThermocoupleType.S, Construction.NONEXPENDABLE, SensorRole.SURVEY, ledger)
    assert result.is_spent
    assert "allowed hours" in result.reason


def test_the_use_limit_bites_before_the_hours_limit() -> None:
    ledger = UsageLedger()
    for _ in range(90):
        ledger.record(
            UsageEvent(
                date(2024, 5, 1), Temperature.fahrenheit(1100), minutes(6), SensorRole.SURVEY
            )
        )
    result = assess(ThermocoupleType.N, Construction.NONEXPENDABLE, SensorRole.SURVEY, ledger)
    assert result.is_spent
    assert "used 90 of 90" in result.reason
