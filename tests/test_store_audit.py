from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from quenchline.errors import ValidationError
from quenchline.store.audit import AuditEntry, AuditTrail
from quenchline.store.database import Database

WHEN = datetime(2025, 9, 1, 9, 30, tzinfo=UTC)


@pytest.fixture()
def trail() -> Iterator[AuditTrail]:
    with Database.in_memory() as database:
        yield AuditTrail(database, actor="dt")


def test_an_entry_needs_its_three_fields() -> None:
    with pytest.raises(ValidationError):
        AuditEntry(WHEN, "  ", "load", "L25-0001")
    with pytest.raises(ValidationError):
        AuditEntry(WHEN, "certified", " ", "L25-0001")
    with pytest.raises(ValidationError):
        AuditEntry(WHEN, "certified", "load", "")


def test_recording_gives_the_entry_an_id(trail: AuditTrail) -> None:
    entry = trail.record("certified", "load", "L25-0001", at=WHEN)
    assert entry.entry_id is not None
    assert entry.actor == "dt"
    assert trail.count() == 1


def test_the_actor_can_be_overridden_per_entry(trail: AuditTrail) -> None:
    entry = trail.record("certified", "load", "L25-0001", at=WHEN, actor="qa")
    assert entry.actor == "qa"
    assert trail.actors() == ["qa"]


def test_entries_come_back_newest_first(trail: AuditTrail) -> None:
    trail.record("planned", "load", "L25-0001", at=WHEN)
    trail.record("certified", "load", "L25-0001", at=WHEN)
    assert [e.action for e in trail.all()] == ["certified", "planned"]


def test_the_limit_is_honoured(trail: AuditTrail) -> None:
    for index in range(5):
        trail.record("planned", "load", f"L25-000{index}", at=WHEN)
    assert len(trail.all(limit=2)) == 2
    with pytest.raises(ValidationError):
        trail.all(limit=0)


def test_the_history_of_one_thing_is_oldest_first(trail: AuditTrail) -> None:
    trail.record("planned", "load", "L25-0001", at=WHEN)
    trail.record("held", "load", "L25-0001", at=WHEN, detail="paperwork")
    trail.record("certified", "load", "L25-0001", at=WHEN)
    trail.record("certified", "load", "L25-0002", at=WHEN)
    history = trail.against("load", "L25-0001")
    assert [e.action for e in history] == ["planned", "held", "certified"]
    assert history[1].detail == "paperwork"


def test_nothing_against_an_unknown_thing(trail: AuditTrail) -> None:
    assert trail.against("load", "L25-9999") == []


def test_entries_can_be_found_by_action(trail: AuditTrail) -> None:
    trail.record("certified", "load", "L25-0001", at=WHEN)
    trail.record("rejected", "load", "L25-0002", at=WHEN)
    assert [e.reference for e in trail.by_action("certified")] == ["L25-0001"]
    assert trail.by_action("scrapped") == []


def test_entries_can_be_windowed(trail: AuditTrail) -> None:
    trail.record("certified", "load", "L25-0001", at=datetime(2025, 3, 1, tzinfo=UTC))
    trail.record("certified", "load", "L25-0002", at=datetime(2025, 9, 1, tzinfo=UTC))
    window = trail.between(datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 6, 1, tzinfo=UTC))
    assert [e.reference for e in window] == ["L25-0001"]


def test_the_time_survives_the_round_trip(trail: AuditTrail) -> None:
    trail.record("certified", "load", "L25-0001", at=WHEN)
    assert trail.all()[0].at == WHEN


def test_recording_without_a_time_uses_now(trail: AuditTrail) -> None:
    entry = trail.record("certified", "load", "L25-0001")
    assert entry.at.tzinfo is not None


def test_entry_text(trail: AuditTrail) -> None:
    entry = trail.record("certified", "load", "L25-0001", at=WHEN)
    assert "dt certified L25-0001" in str(entry)


def test_an_entry_with_no_actor_reads_as_someone() -> None:
    assert "someone certified" in str(AuditEntry(WHEN, "certified", "load", "L25-0001"))


def test_the_trail_offers_no_way_to_delete_an_entry() -> None:
    assert not hasattr(AuditTrail, "delete")
    assert not hasattr(AuditTrail, "update")
