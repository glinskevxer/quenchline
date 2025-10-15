from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

import pytest

from quenchline.errors import NotFoundError
from quenchline.identity import FurnaceTag, LotNumber, WorkOrder
from quenchline.loads.deviation import Deviation, DeviationKind, Severity
from quenchline.loads.disposition import Decision, Disposition
from quenchline.loads.record import Load, LoadState, PartLine
from quenchline.store.database import Database
from quenchline.store.grading import GradingRepository
from quenchline.store.loads import LoadRepository

GRADED = date(2025, 10, 10)


@pytest.fixture()
def repos() -> Iterator[tuple[GradingRepository, LoadRepository]]:
    with Database.in_memory() as database:
        yield GradingRepository(database), LoadRepository(database)


def load(lot: str = "L25-0001", furnace: str = "HT-04") -> Load:
    return Load(
        lot=LotNumber.parse(lot),
        work_order=WorkOrder.parse("W104417"),
        furnace=FurnaceTag.parse(furnace),
        recipe_code="HT-4140-Q",
        recipe_revision="C",
        parts=(PartLine("PN-8891", 10),),
        state=LoadState.COMPLETE,
        finished_at=datetime(2025, 10, 9, 12, 0),
        trace_source="run.csv",
    )


def finding(
    kind: DeviationKind = DeviationKind.SHORT_SOAK,
    severity: Severity = Severity.MAJOR,
    step: str = "austenitise",
) -> Deviation:
    return Deviation(kind, step, "held 0:50 of a required 1:00", severity)


def decision(disposition: Disposition = Disposition.REWORK) -> Decision:
    return Decision(disposition, "can be put right by running the cycle again")


def test_a_grading_round_trips(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load())
    grading.record(load(), (finding(),), decision(), GRADED)
    stored = grading.get("L25-0001")
    assert stored.graded_on == GRADED
    assert stored.recipe == "HT-4140-Q rev C"
    assert stored.disposition is Disposition.REWORK
    assert len(stored.findings) == 1
    assert stored.findings[0].kind is DeviationKind.SHORT_SOAK
    assert stored.worst is Severity.MAJOR


def test_a_clean_run_stores_no_findings(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load())
    grading.record(load(), (), Decision(Disposition.ACCEPT, "no deviations"), GRADED)
    stored = grading.get("L25-0001")
    assert stored.findings == ()
    assert stored.worst is None


def test_regrading_replaces_the_findings(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load())
    grading.record(load(), (finding(), finding()), decision(), GRADED)
    grading.record(load(), (finding(),), decision(Disposition.ACCEPT_AS_IS), GRADED)
    stored = grading.get("L25-0001")
    assert len(stored.findings) == 1
    assert stored.disposition is Disposition.ACCEPT_AS_IS
    assert grading.finding_count() == 1


def test_an_ungraded_load_is_not_found(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, _ = repos
    assert not grading.exists("L25-0001")
    with pytest.raises(NotFoundError):
        grading.get("L25-0001")


def test_a_short_lot_number_finds_the_grading(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load())
    grading.record(load(), (), decision(), GRADED)
    assert grading.exists("l25-0001")


def test_finished_loads_awaiting_grading_are_listed(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load("L25-0001"))
    loads.insert(load("L25-0002"))
    grading.record(load("L25-0001"), (), decision(), GRADED)
    assert grading.ungraded() == ["L25-0002"]


def test_an_unfinished_load_is_not_awaiting_grading(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    unfinished = Load(
        lot=LotNumber.parse("L25-0003"),
        work_order=WorkOrder.parse("W104417"),
        furnace=FurnaceTag.parse("HT-04"),
        recipe_code="HT-4140-Q",
        recipe_revision="C",
    )
    loads.insert(unfinished)
    assert grading.ungraded() == []


def test_findings_are_counted_by_kind(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load("L25-0001"))
    loads.insert(load("L25-0002"))
    grading.record(
        load("L25-0001"),
        (finding(), finding(DeviationKind.SENSOR_LOST)),
        decision(),
        GRADED,
    )
    grading.record(load("L25-0002"), (finding(),), decision(), GRADED)
    counts = grading.counts_by_kind()
    assert counts["short_soak"] == 2
    assert counts["sensor_lost"] == 1
    assert list(counts)[0] == "short_soak"


def test_findings_are_counted_by_furnace(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load("L25-0001", "HT-04"))
    loads.insert(load("L25-0002", "HT-04"))
    loads.insert(load("L25-0003", "HT-11"))
    for lot in ("L25-0001", "L25-0002"):
        grading.record(load(lot, "HT-04"), (finding(),), decision(), GRADED)
    grading.record(load("L25-0003", "HT-11"), (finding(),), decision(), GRADED)
    counts = grading.counts_by_furnace()
    assert counts["HT-04"] == 2
    assert counts["HT-11"] == 1


def test_one_kind_can_be_counted_by_furnace(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load("L25-0001", "HT-04"))
    loads.insert(load("L25-0002", "HT-11"))
    grading.record(load("L25-0001", "HT-04"), (finding(),), decision(), GRADED)
    grading.record(
        load("L25-0002", "HT-11"),
        (finding(DeviationKind.SENSOR_LOST),),
        decision(),
        GRADED,
    )
    counts = grading.counts_by_furnace(DeviationKind.SHORT_SOAK)
    assert counts == {"HT-04": 1}


def test_runs_can_be_filtered_by_disposition(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load("L25-0001"))
    loads.insert(load("L25-0002"))
    grading.record(load("L25-0001"), (), Decision(Disposition.ACCEPT, "clean"), GRADED)
    grading.record(load("L25-0002"), (finding(),), decision(), GRADED)
    assert [r.lot for r in grading.with_disposition(Disposition.REWORK)] == ["L25-0002"]
    assert [r.lot for r in grading.all()] == ["L25-0001", "L25-0002"]


def test_deleting_the_load_takes_the_grading(
    repos: tuple[GradingRepository, LoadRepository],
) -> None:
    grading, loads = repos
    loads.insert(load())
    grading.record(load(), (finding(),), decision(), GRADED)
    loads.delete("L25-0001")
    assert grading.count() == 0
    assert grading.finding_count() == 0
