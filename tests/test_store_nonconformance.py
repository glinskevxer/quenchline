from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.loads.disposition import Disposition
from quenchline.nonconformance.record import NcrStage, NcrSubject, Nonconformance
from quenchline.store.database import Database
from quenchline.store.nonconformance import NcrRepository

RAISED = date(2025, 1, 8)


@pytest.fixture()
def repo() -> Iterator[NcrRepository]:
    with Database.in_memory() as database:
        yield NcrRepository(database)


def ncr(number: str = "NCR-25-014", **changes: object) -> Nonconformance:
    base: dict[str, object] = {
        "number": number,
        "subject": NcrSubject.LOAD,
        "reference": "L24-0917",
        "raised_on": RAISED,
        "summary": "soak short by twelve minutes",
    }
    base.update(changes)
    return Nonconformance(**base)  # type: ignore[arg-type]


def test_a_report_round_trips(repo: NcrRepository) -> None:
    repo.insert(ncr())
    loaded = repo.get("NCR-25-014")
    assert loaded.subject is NcrSubject.LOAD
    assert loaded.reference == "L24-0917"
    assert loaded.raised_on == RAISED
    assert loaded.stage is NcrStage.RAISED
    assert loaded.disposition is None


def test_a_disposition_round_trips(repo: NcrRepository) -> None:
    repo.insert(ncr().disposition_as(Disposition.SCRAP, date(2025, 1, 9)))
    assert repo.get("NCR-25-014").disposition is Disposition.SCRAP


def test_a_suspect_window_round_trips(repo: NcrRepository) -> None:
    repo.insert(
        ncr(subject=NcrSubject.INSTRUMENT, reference="IC-04").with_suspect_window(
            date(2024, 10, 1), RAISED
        )
    )
    loaded = repo.get("NCR-25-014")
    assert loaded.suspect_from == date(2024, 10, 1)
    assert loaded.suspect_to == RAISED


def test_entries_are_not_stored(repo: NcrRepository) -> None:
    repo.insert(ncr().note("customer informed"))
    assert repo.get("NCR-25-014").entries == ()


def test_inserting_twice_is_a_conflict(repo: NcrRepository) -> None:
    repo.insert(ncr())
    with pytest.raises(ConflictError):
        repo.insert(ncr())


def test_save_replaces_the_record(repo: NcrRepository) -> None:
    repo.insert(ncr())
    repo.save(ncr().disposition_as(Disposition.REWORK, date(2025, 1, 9)))
    assert repo.get("NCR-25-014").stage is NcrStage.DISPOSITIONED
    assert repo.count() == 1


def test_unknown_reports(repo: NcrRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("NCR-25-999")
    with pytest.raises(NotFoundError):
        repo.delete("NCR-25-999")


def test_listing_helpers(repo: NcrRepository) -> None:
    repo.insert(ncr("NCR-25-001"))
    repo.insert(ncr("NCR-25-002", subject=NcrSubject.INSTRUMENT, reference="IC-04"))
    assert [r.number for r in repo.all()] == ["NCR-25-001", "NCR-25-002"]
    assert [r.number for r in repo.about(NcrSubject.INSTRUMENT)] == ["NCR-25-002"]
    assert [r.number for r in repo.against("IC-04")] == ["NCR-25-002"]


def test_open_reports_exclude_the_finished_ones(repo: NcrRepository) -> None:
    repo.insert(ncr("NCR-25-001"))
    closed = (
        ncr("NCR-25-002")
        .disposition_as(Disposition.REWORK, date(2025, 1, 9))
        .action(date(2025, 1, 10), "rerun")
        .close(date(2025, 1, 11))
    )
    repo.insert(closed)
    repo.insert(ncr("NCR-25-003").void("duplicate"))
    assert [r.number for r in repo.open_reports()] == ["NCR-25-001"]


def test_raised_between_windows_the_register(repo: NcrRepository) -> None:
    repo.insert(ncr("NCR-25-001", raised_on=date(2025, 1, 8)))
    repo.insert(ncr("NCR-25-002", raised_on=date(2025, 3, 8)))
    window = repo.raised_between(date(2025, 1, 1), date(2025, 1, 31))
    assert [r.number for r in window] == ["NCR-25-001"]


def test_reports_with_suspect_windows_are_findable(repo: NcrRepository) -> None:
    repo.insert(ncr("NCR-25-001"))
    repo.insert(
        ncr("NCR-25-002", subject=NcrSubject.SENSOR, reference="TC-00001").with_suspect_window(
            date(2024, 10, 1), RAISED
        )
    )
    assert [r.number for r in repo.with_suspect_windows()] == ["NCR-25-002"]


def test_delete_removes_the_report(repo: NcrRepository) -> None:
    repo.insert(ncr())
    repo.delete("NCR-25-014")
    assert repo.count() == 0


def test_the_first_number_of_a_year(repo: NcrRepository) -> None:
    assert repo.next_number(2025) == "NCR-25-001"


def test_numbers_increment_within_a_year(repo: NcrRepository) -> None:
    repo.insert(ncr("NCR-25-001"))
    repo.insert(ncr("NCR-25-002"))
    assert repo.next_number(2025) == "NCR-25-003"


def test_numbers_restart_in_a_new_year(repo: NcrRepository) -> None:
    repo.insert(ncr("NCR-25-014"))
    assert repo.next_number(2026) == "NCR-26-001"
    assert repo.next_number(2025) == "NCR-25-015"


def test_numbering_survives_a_gap(repo: NcrRepository) -> None:
    repo.insert(ncr("NCR-25-001"))
    repo.insert(ncr("NCR-25-009"))
    assert repo.next_number(2025) == "NCR-25-010"
