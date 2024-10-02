from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag
from quenchline.temperature import Temperature
from quenchline.tus.history import SurveyHistory, SurveyOutcome, range_from

FURNACE = FurnaceTag.parse("HT-04")


def outcome(
    number: str,
    performed: date,
    passed: bool,
    passing: list[float],
    failing: list[float] | None = None,
) -> SurveyOutcome:
    return SurveyOutcome(
        number,
        performed,
        passed,
        tuple(Temperature.fahrenheit(v) for v in passing),
        tuple(Temperature.fahrenheit(v) for v in (failing or [])),
    )


def history(
    furnace_class: FurnaceClass = FurnaceClass.CLASS_3,
    instrumentation: InstrumentationType = InstrumentationType.C,
) -> SurveyHistory:
    return SurveyHistory(FURNACE, "main", furnace_class, instrumentation)


def test_outcome_validation() -> None:
    with pytest.raises(ValidationError):
        outcome("  ", date(2024, 9, 1), True, [1550.0])
    with pytest.raises(ValidationError):
        outcome("TUS-1", date(2024, 9, 1), True, [1550.0], [1700.0])


def test_a_single_setpoint_earns_a_narrow_band() -> None:
    qualified = range_from((Temperature.fahrenheit(1550),))
    assert qualified is not None
    assert qualified.low.degf == pytest.approx(1525.0)
    assert qualified.high.degf == pytest.approx(1575.0)


def test_two_setpoints_earn_everything_between() -> None:
    qualified = range_from((Temperature.fahrenheit(1200), Temperature.fahrenheit(1700)))
    assert qualified is not None
    assert qualified.low.degf == pytest.approx(1200.0)
    assert qualified.high.degf == pytest.approx(1700.0)


def test_no_setpoints_earn_nothing() -> None:
    assert range_from(()) is None


def test_an_empty_history_qualifies_nothing() -> None:
    h = history()
    assert h.is_empty
    assert h.qualified() is None
    assert h.latest_pass() is None
    assert h.due(date(2024, 10, 1)).never_surveyed
    assert not h.may_run(Temperature.fahrenheit(1550), date(2024, 10, 1))


def test_the_same_survey_cannot_be_filed_twice() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 9, 1), True, [1550.0]))
    with pytest.raises(ValidationError):
        h.file(outcome("TUS-1", date(2024, 10, 1), True, [1550.0]))


def test_filing_keeps_the_history_in_order() -> None:
    h = history()
    h.file(outcome("TUS-2", date(2024, 9, 1), True, [1550.0]))
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1550.0]))
    assert [o.number for o in h.outcomes] == ["TUS-1", "TUS-2"]


def test_a_passing_survey_qualifies_the_range_it_covered() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 9, 1), True, [1200.0, 1700.0]))
    qualified = h.qualified()
    assert qualified is not None
    assert qualified.covers(Temperature.fahrenheit(1550))
    assert not qualified.covers(Temperature.fahrenheit(1750))


def test_a_partial_failure_collapses_the_range_to_what_passed() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1200.0, 1700.0]))
    h.file(outcome("TUS-2", date(2024, 9, 1), False, [1200.0], [1700.0]))
    qualified = h.qualified()
    assert qualified is not None
    assert qualified.covers(Temperature.fahrenheit(1200))
    assert not qualified.covers(Temperature.fahrenheit(1550))


def test_a_total_failure_leaves_nothing_qualified() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1200.0, 1700.0]))
    h.file(outcome("TUS-2", date(2024, 9, 1), False, [], [1200.0, 1700.0]))
    assert h.qualified() is None


def test_only_the_newest_survey_qualifies_the_furnace() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1200.0, 1900.0]))
    h.file(outcome("TUS-2", date(2024, 9, 1), True, [1200.0, 1600.0]))
    qualified = h.qualified()
    assert qualified is not None
    assert not qualified.covers(Temperature.fahrenheit(1800))


def test_the_interval_comes_off_the_class_and_instrumentation() -> None:
    assert history().interval().count == 6
    assert history(instrumentation=InstrumentationType.A).interval().count == 12
    assert history(instrumentation=InstrumentationType.E).interval().count == 3


def test_a_run_of_passes_stretches_the_interval() -> None:
    h = history()
    for index in range(3):
        h.file(outcome(f"TUS-{index}", date(2023, 1 + index, 1), True, [1550.0]))
    assert h.interval().count == 12


def test_a_failure_resets_the_run() -> None:
    h = history()
    for index in range(3):
        h.file(outcome(f"TUS-{index}", date(2023, 1 + index, 1), True, [1550.0]))
    h.file(outcome("TUS-bad", date(2023, 6, 1), False, [], [1550.0]))
    assert h.consecutive_passes() == 0
    assert h.interval().count == 6


def test_the_due_date_hangs_off_the_last_pass() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1550.0]))
    due = h.due(date(2024, 6, 1))
    assert due.due == date(2024, 9, 1)
    assert due.days_left == 92
    assert not due.overdue


def test_a_later_failure_does_not_move_the_due_date() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1550.0]))
    h.file(outcome("TUS-2", date(2024, 8, 1), False, [], [1550.0]))
    assert h.due(date(2024, 8, 2)).last_passed == date(2024, 3, 1)


def test_grace_delays_the_overdue_flag() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1550.0]))
    assert h.due(date(2024, 9, 10)).overdue
    assert not h.due(date(2024, 9, 10), grace=30).overdue


def test_may_run_needs_both_a_live_survey_and_the_range() -> None:
    h = history()
    h.file(outcome("TUS-1", date(2024, 3, 1), True, [1200.0, 1700.0]))
    assert h.may_run(Temperature.fahrenheit(1550), date(2024, 6, 1))
    assert not h.may_run(Temperature.fahrenheit(1800), date(2024, 6, 1))
    assert not h.may_run(Temperature.fahrenheit(1550), date(2025, 6, 1))
