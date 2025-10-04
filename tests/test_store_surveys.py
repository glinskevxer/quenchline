from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag
from quenchline.store.database import Database
from quenchline.store.surveys import SurveyRepository
from quenchline.temperature import Temperature
from quenchline.tus.history import SurveyOutcome


@pytest.fixture()
def repo() -> Iterator[SurveyRepository]:
    with Database.in_memory() as database:
        yield SurveyRepository(database)


def outcome(
    number: str = "TUS-25-004",
    performed: date = date(2025, 6, 1),
    passed: bool = True,
    passing: tuple[float, ...] = (1200.0, 1700.0),
    failing: tuple[float, ...] = (),
) -> SurveyOutcome:
    return SurveyOutcome(
        number,
        performed,
        passed,
        tuple(Temperature.fahrenheit(v) for v in passing),
        tuple(Temperature.fahrenheit(v) for v in failing),
    )


def test_an_outcome_round_trips(repo: SurveyRepository) -> None:
    repo.insert(outcome(), "HT-04", "main")
    loaded = repo.get("TUS-25-004")
    assert loaded.performed == date(2025, 6, 1)
    assert loaded.passed
    assert [t.degf for t in loaded.passing_setpoints] == [1200.0, 1700.0]
    assert loaded.failing_setpoints == ()


def test_a_partial_failure_keeps_both_lists(repo: SurveyRepository) -> None:
    repo.insert(outcome(passed=False, passing=(1200.0,), failing=(1700.0,)), "HT-04", "main")
    loaded = repo.get("TUS-25-004")
    assert not loaded.passed
    assert [t.degf for t in loaded.passing_setpoints] == [1200.0]
    assert [t.degf for t in loaded.failing_setpoints] == [1700.0]


def test_a_total_failure_has_no_passing_setpoints(repo: SurveyRepository) -> None:
    repo.insert(outcome(passed=False, passing=(), failing=(1200.0, 1700.0)), "HT-04", "main")
    assert repo.get("TUS-25-004").passing_setpoints == ()


def test_inserting_twice_conflicts(repo: SurveyRepository) -> None:
    repo.insert(outcome(), "HT-04", "main")
    with pytest.raises(ConflictError):
        repo.insert(outcome(), "HT-04", "main")


def test_an_unknown_survey_is_not_found(repo: SurveyRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("TUS-25-999")
    with pytest.raises(NotFoundError):
        repo.delete("TUS-25-999")


def test_surveys_are_grouped_by_zone(repo: SurveyRepository) -> None:
    repo.insert(outcome("TUS-25-001"), "HT-04", "main")
    repo.insert(outcome("TUS-25-002"), "HT-04", "rear")
    repo.insert(outcome("TUS-25-003"), "HT-11", "main")
    assert repo.zones() == [("HT-04", "main"), ("HT-04", "rear"), ("HT-11", "main")]
    assert [o.number for o in repo.for_zone("HT-04", "main")] == ["TUS-25-001"]
    assert [o.number for o in repo.for_zone("ht-4", "rear")] == ["TUS-25-002"]


def test_the_history_is_rebuilt_in_date_order(repo: SurveyRepository) -> None:
    repo.insert(outcome("TUS-25-002", performed=date(2025, 9, 1)), "HT-04", "main")
    repo.insert(outcome("TUS-25-001", performed=date(2025, 3, 1)), "HT-04", "main")
    history = repo.history("HT-04", "main", FurnaceClass.CLASS_3, InstrumentationType.C)
    assert [o.number for o in history.outcomes] == ["TUS-25-001", "TUS-25-002"]
    assert history.consecutive_passes() == 2


def test_the_history_qualifies_off_the_newest_survey(repo: SurveyRepository) -> None:
    repo.insert(
        outcome("TUS-25-001", performed=date(2025, 3, 1), passing=(1200.0, 1900.0)),
        "HT-04",
        "main",
    )
    repo.insert(
        outcome("TUS-25-002", performed=date(2025, 9, 1), passing=(1200.0, 1600.0)),
        "HT-04",
        "main",
    )
    qualified = repo.history(
        "HT-04", "main", FurnaceClass.CLASS_3, InstrumentationType.C
    ).qualified()
    assert qualified is not None
    assert not qualified.covers(Temperature.fahrenheit(1800))


def test_a_zone_with_no_surveys_gives_an_empty_history(repo: SurveyRepository) -> None:
    history = repo.history(
        FurnaceTag.parse("HT-99"), "main", FurnaceClass.CLASS_3, InstrumentationType.C
    )
    assert history.is_empty


def test_save_replaces_the_setpoints(repo: SurveyRepository) -> None:
    repo.insert(outcome(), "HT-04", "main")
    repo.save(outcome(passing=(1550.0,)), "HT-04", "main")
    loaded = repo.get("TUS-25-004")
    assert [t.degf for t in loaded.passing_setpoints] == [1550.0]
    assert repo.count() == 1


def test_delete_takes_the_setpoints(repo: SurveyRepository) -> None:
    repo.insert(outcome(), "HT-04", "main")
    repo.delete("TUS-25-004")
    assert repo.count() == 0
    assert repo.database.query("SELECT setpoint_f FROM survey_setpoint") == []
