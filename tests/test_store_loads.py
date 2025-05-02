from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.identity import FurnaceTag, LotNumber, WorkOrder
from quenchline.loads.record import Load, LoadState, PartLine
from quenchline.measure import Mass
from quenchline.store.database import Database
from quenchline.store.loads import LoadRepository

CHARGED = datetime(2024, 11, 4, 6, 30)
STARTED = datetime(2024, 11, 4, 7, 0)
FINISHED = datetime(2024, 11, 4, 12, 0)


@pytest.fixture()
def repo() -> Iterator[LoadRepository]:
    with Database.in_memory() as database:
        yield LoadRepository(database)


def load(lot: str = "L24-0917", **changes: object) -> Load:
    base: dict[str, object] = {
        "lot": LotNumber.parse(lot),
        "work_order": WorkOrder.parse("W104417"),
        "furnace": FurnaceTag.parse("HT-04"),
        "recipe_code": "HT-4140-Q",
        "recipe_revision": "C",
        "parts": (PartLine("PN-8891", 40, "4140", "pinion shaft"),),
        "weight": Mass.pounds(1450),
        "state": LoadState.COMPLETE,
        "charged_at": CHARGED,
        "started_at": STARTED,
        "finished_at": FINISHED,
    }
    base.update(changes)
    return Load(**base)  # type: ignore[arg-type]


def test_a_load_round_trips(repo: LoadRepository) -> None:
    repo.insert(load())
    loaded = repo.get("L24-0917")
    assert str(loaded.work_order) == "W104417"
    assert str(loaded.furnace) == "HT-04"
    assert loaded.recipe == "HT-4140-Q rev C"
    assert loaded.state is LoadState.COMPLETE


def test_the_times_round_trip(repo: LoadRepository) -> None:
    repo.insert(load())
    loaded = repo.get("L24-0917")
    assert loaded.charged_at == CHARGED
    assert loaded.started_at == STARTED
    assert loaded.finished_at == FINISHED


def test_a_planned_load_has_no_times(repo: LoadRepository) -> None:
    repo.insert(
        load(state=LoadState.PLANNED, charged_at=None, started_at=None, finished_at=None)
    )
    loaded = repo.get("L24-0917")
    assert loaded.charged_at is None
    assert loaded.finished_at is None


def test_the_weight_round_trips(repo: LoadRepository) -> None:
    repo.insert(load())
    weight = repo.get("L24-0917").weight
    assert weight is not None
    assert weight.pounds_value == pytest.approx(1450.0)


def test_a_load_with_no_weight_round_trips(repo: LoadRepository) -> None:
    repo.insert(load(weight=None))
    assert repo.get("L24-0917").weight is None


def test_parts_round_trip(repo: LoadRepository) -> None:
    repo.insert(
        load(
            parts=(
                PartLine("PN-8892", 12, "4140"),
                PartLine("PN-8891", 40, "4140", "pinion shaft"),
            )
        )
    )
    loaded = repo.get("L24-0917")
    assert [p.part_number for p in loaded.parts] == ["PN-8891", "PN-8892"]
    assert loaded.piece_count == 52
    assert loaded.parts[0].description == "pinion shaft"


def test_a_load_with_no_parts_round_trips(repo: LoadRepository) -> None:
    repo.insert(load(parts=()))
    assert repo.get("L24-0917").parts == ()


def test_inserting_twice_is_a_conflict(repo: LoadRepository) -> None:
    repo.insert(load())
    with pytest.raises(ConflictError):
        repo.insert(load())


def test_save_replaces_the_record_and_the_parts(repo: LoadRepository) -> None:
    repo.insert(load())
    repo.save(load(parts=(PartLine("PN-9000", 5),), state=LoadState.CERTIFIED))
    loaded = repo.get("L24-0917")
    assert [p.part_number for p in loaded.parts] == ["PN-9000"]
    assert loaded.state is LoadState.CERTIFIED
    assert repo.count() == 1


def test_an_unknown_load_is_not_found(repo: LoadRepository) -> None:
    with pytest.raises(NotFoundError):
        repo.get("L24-9999")
    with pytest.raises(NotFoundError):
        repo.delete("L24-9999")


def test_listing_helpers(repo: LoadRepository) -> None:
    repo.insert(load("L24-0917"))
    repo.insert(load("L24-0918", state=LoadState.CERTIFIED))
    repo.insert(
        load(
            "L24-0919", furnace=FurnaceTag.parse("HT-11"), work_order=WorkOrder.parse("W104418")
        )
    )
    assert [str(item.lot) for item in repo.all()] == ["L24-0917", "L24-0918", "L24-0919"]
    assert [str(item.lot) for item in repo.in_state(LoadState.CERTIFIED)] == ["L24-0918"]
    assert [str(item.lot) for item in repo.on_furnace("HT-11")] == ["L24-0919"]
    assert [str(item.lot) for item in repo.for_work_order("W104418")] == ["L24-0919"]


def test_recipe_lookup_by_code_and_revision(repo: LoadRepository) -> None:
    repo.insert(load("L24-0917"))
    repo.insert(load("L24-0918", recipe_revision="D"))
    repo.insert(load("L24-0919", recipe_code="HT-8620-C"))
    assert len(repo.to_recipe("HT-4140-Q")) == 2
    assert [str(item.lot) for item in repo.to_recipe("HT-4140-Q", "D")] == ["L24-0918"]


def test_finished_loads_can_be_windowed(repo: LoadRepository) -> None:
    repo.insert(load("L24-0917"))
    repo.insert(load("L24-0918", finished_at=datetime(2024, 12, 1, 9, 0)))
    repo.insert(load("L24-0919", state=LoadState.PLANNED, finished_at=None))
    window = repo.between(datetime(2024, 11, 1), datetime(2024, 11, 30))
    assert [str(item.lot) for item in window] == ["L24-0917"]


def test_delete_takes_the_parts(repo: LoadRepository) -> None:
    repo.insert(load())
    repo.delete("L24-0917")
    assert repo.count() == 0
    assert repo.piece_count() == 0


def test_piece_count_sums_across_loads(repo: LoadRepository) -> None:
    repo.insert(load("L24-0917"))
    repo.insert(load("L24-0918", parts=(PartLine("PN-9000", 5),)))
    assert repo.piece_count() == 45


def test_lookups_accept_an_untidy_tag(repo: LoadRepository) -> None:
    repo.insert(load())
    assert [str(item.lot) for item in repo.on_furnace("ht-4")] == ["L24-0917"]
    assert [str(item.lot) for item in repo.for_work_order("w104417")] == ["L24-0917"]


def test_the_trace_reference_round_trips(repo: LoadRepository) -> None:
    from quenchline.loads.trace import Channel, ChannelRole, Trace
    from quenchline.timespan import minutes

    trace = Trace(
        datetime(2024, 11, 4, 7, 0),
        (Channel.of("C1", ChannelRole.CONTROL, [(minutes(0), 100.0), (minutes(30), 1550.0)]),),
        "run-2411.csv",
    )
    repo.insert(load(state=LoadState.RUNNING).attach(trace, digest="deadbeef"))
    loaded = repo.get("L24-0917")
    assert loaded.trace_source == "run-2411.csv"
    assert loaded.trace_digest == "deadbeef"
    assert [str(item.lot) for item in repo.with_trace_digest("deadbeef")] == ["L24-0917"]


def test_a_load_with_no_trace_reference_comes_back_blank(repo: LoadRepository) -> None:
    repo.insert(load())
    loaded = repo.get("L24-0917")
    assert loaded.trace_source == ""
    assert loaded.trace_digest == ""
    assert repo.with_trace_digest("deadbeef") == []
