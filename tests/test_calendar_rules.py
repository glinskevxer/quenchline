from __future__ import annotations

from datetime import date

import pytest

from quenchline.calendar_rules import (
    DueRule,
    Interval,
    IntervalUnit,
    add_months,
    clamp_to_month_end,
    days_in_month,
    days_until,
    due_date,
    end_of_month,
    is_overdue,
    start_of_month,
)
from quenchline.errors import ValidationError


def test_days_in_month_handles_leap_years() -> None:
    assert days_in_month(2024, 2) == 29
    assert days_in_month(2025, 2) == 28
    assert days_in_month(2024, 1) == 31


def test_month_edges() -> None:
    assert end_of_month(date(2024, 2, 14)) == date(2024, 2, 29)
    assert end_of_month(date(2025, 2, 14)) == date(2025, 2, 28)
    assert start_of_month(date(2024, 2, 14)) == date(2024, 2, 1)


def test_add_months_clamps_rather_than_rolling_over() -> None:
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_months(date(2024, 3, 31), 1) == date(2024, 4, 30)


def test_add_months_crosses_years_in_both_directions() -> None:
    assert add_months(date(2024, 11, 15), 3) == date(2025, 2, 15)
    assert add_months(date(2024, 2, 15), -3) == date(2023, 11, 15)
    assert add_months(date(2024, 6, 1), 24) == date(2026, 6, 1)


def test_interval_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Interval(0, IntervalUnit.DAY)


def test_interval_after_by_unit() -> None:
    start = date(2024, 3, 14)
    assert Interval.days(10).after(start) == date(2024, 3, 24)
    assert Interval.weeks(2).after(start) == date(2024, 3, 28)
    assert Interval.months(3).after(start) == date(2024, 6, 14)
    assert Interval.years(1).after(start) == date(2025, 3, 14)


def test_interval_scaling() -> None:
    assert Interval.months(3).scaled(2.0) == Interval.months(6)
    assert Interval.months(3).scaled(0.5) == Interval.months(1)
    with pytest.raises(ValidationError):
        Interval.months(1).scaled(0.4)


def test_approximate_days_is_only_for_sorting() -> None:
    assert Interval.days(10).approximate_days == 10
    assert Interval.weeks(2).approximate_days == 14
    assert Interval.months(3).approximate_days == 90
    assert Interval.years(1).approximate_days == 365


def test_interval_formatting() -> None:
    assert str(Interval.months(3)) == "3 months"
    assert str(Interval.days(1)) == "1 day"


def test_anniversary_rule() -> None:
    assert due_date(date(2024, 3, 14), Interval.months(3)) == date(2024, 6, 14)


def test_end_of_month_rule_pulls_everything_to_the_month_end() -> None:
    early = due_date(date(2024, 3, 2), Interval.months(3), DueRule.END_OF_MONTH)
    late = due_date(date(2024, 3, 27), Interval.months(3), DueRule.END_OF_MONTH)
    assert early == late == date(2024, 6, 30)


def test_start_of_month_rule_is_the_following_first() -> None:
    assert due_date(date(2024, 3, 2), Interval.months(3), DueRule.START_OF_MONTH) == date(
        2024, 7, 1
    )


def test_end_of_month_rule_across_a_year_boundary() -> None:
    assert due_date(date(2024, 11, 14), Interval.months(3), DueRule.END_OF_MONTH) == date(
        2025, 2, 28
    )


def test_days_until_is_signed() -> None:
    assert days_until(date(2024, 6, 14), date(2024, 6, 1)) == 13
    assert days_until(date(2024, 6, 14), date(2024, 6, 20)) == -6
    assert days_until(date(2024, 6, 14), date(2024, 6, 14)) == 0


def test_overdue_on_the_due_date_itself_is_not_overdue() -> None:
    assert not is_overdue(date(2024, 6, 14), date(2024, 6, 14))
    assert is_overdue(date(2024, 6, 14), date(2024, 6, 15))


def test_grace_pushes_the_overdue_point_out() -> None:
    due = date(2024, 6, 14)
    assert not is_overdue(due, date(2024, 6, 20), grace=7)
    assert is_overdue(due, date(2024, 6, 22), grace=7)


def test_negative_grace_is_refused() -> None:
    with pytest.raises(ValidationError):
        is_overdue(date(2024, 6, 14), date(2024, 6, 15), grace=-1)


def test_clamp_to_month_end() -> None:
    assert clamp_to_month_end(date(2024, 2, 15)) == date(2024, 2, 15)
    assert clamp_to_month_end(date(2024, 2, 29)) == date(2024, 2, 29)
