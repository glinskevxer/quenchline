from __future__ import annotations

from datetime import date, datetime

import pytest

from quenchline.analysis.workload import Workload, measure, occupied_by
from quenchline.errors import ValidationError
from quenchline.identity import FurnaceTag, LotNumber, WorkOrder
from quenchline.loads.record import Load, LoadState, PartLine

START = date(2025, 5, 1)
END = date(2025, 5, 7)


def load(
    lot: str,
    furnace: str = "HT-04",
    charged: datetime | None = datetime(2025, 5, 2, 6, 0),
    finished: datetime | None = datetime(2025, 5, 2, 12, 0),
    state: LoadState = LoadState.CERTIFIED,
    pieces: int = 10,
) -> Load:
    return Load(
        lot=LotNumber.parse(lot),
        work_order=WorkOrder.parse("W104417"),
        furnace=FurnaceTag.parse(furnace),
        recipe_code="HT-4140-Q",
        recipe_revision="C",
        parts=(PartLine("PN-8891", pieces),),
        state=state,
        charged_at=charged,
        finished_at=finished,
    )


def test_occupied_is_charged_to_finished() -> None:
    assert occupied_by(load("L25-0001")).hours == pytest.approx(6.0)


def test_an_unfinished_load_occupies_nothing() -> None:
    assert occupied_by(load("L25-0001", finished=None)).seconds == pytest.approx(0.0)
    assert occupied_by(load("L25-0001", charged=None)).seconds == pytest.approx(0.0)


def test_a_period_running_backwards_is_refused() -> None:
    with pytest.raises(ValidationError):
        measure([], END, START)
    with pytest.raises(ValidationError):
        Workload(END, START, ())


def test_the_period_length_is_in_hours() -> None:
    assert measure([], START, END).period_hours == pytest.approx(168.0)


def test_loads_outside_the_window_are_ignored() -> None:
    result = measure(
        [load("L25-0001"), load("L25-0002", finished=datetime(2025, 6, 2, 12, 0))],
        START,
        END,
    )
    assert result.total_loads == 1


def test_unfinished_loads_are_ignored() -> None:
    result = measure([load("L25-0001", finished=None)], START, END)
    assert result.furnaces == ()
    assert result.busiest is None
    assert result.quietest is None


def test_loads_are_grouped_by_furnace() -> None:
    result = measure(
        [
            load("L25-0001", "HT-04"),
            load("L25-0002", "HT-04"),
            load("L25-0003", "HT-11"),
        ],
        START,
        END,
    )
    assert [entry.furnace for entry in result.furnaces] == ["HT-04", "HT-11"]
    assert result.for_furnace("HT-04") is not None
    assert result.for_furnace("HT-04").loads == 2  # type: ignore[union-attr]
    assert result.for_furnace("HT-99") is None


def test_pieces_and_verdicts_are_counted() -> None:
    result = measure(
        [
            load("L25-0001", pieces=10),
            load("L25-0002", pieces=32, state=LoadState.REJECTED),
        ],
        START,
        END,
    )
    entry = result.furnaces[0]
    assert entry.pieces == 42
    assert entry.certified == 1
    assert entry.rejected == 1
    assert entry.finished == 2


def test_occupancy_is_a_fraction_of_the_period() -> None:
    result = measure([load("L25-0001")], START, END)
    entry = result.furnaces[0]
    assert entry.occupancy(result.period_hours) == pytest.approx(6.0 / 168.0)


def test_a_zero_length_period_is_refused_by_occupancy() -> None:
    result = measure([load("L25-0001")], START, END)
    with pytest.raises(ValidationError):
        result.furnaces[0].occupancy(0.0)


def test_the_busiest_and_quietest_furnaces_are_found() -> None:
    result = measure(
        [
            load("L25-0001", "HT-04"),
            load(
                "L25-0002",
                "HT-11",
                charged=datetime(2025, 5, 2, 6, 0),
                finished=datetime(2025, 5, 3, 6, 0),
            ),
        ],
        START,
        END,
    )
    busiest = result.busiest
    quietest = result.quietest
    assert busiest is not None and busiest.furnace == "HT-11"
    assert quietest is not None and quietest.furnace == "HT-04"


def test_overlapping_loads_show_as_overbooked_rather_than_being_clamped() -> None:
    long_load = load(
        "L25-0001",
        charged=datetime(2025, 5, 1, 0, 0),
        finished=datetime(2025, 5, 7, 0, 0),
    )
    second = load(
        "L25-0002",
        charged=datetime(2025, 5, 1, 0, 0),
        finished=datetime(2025, 5, 7, 0, 0),
    )
    result = measure([long_load, second], START, END)
    entry = result.furnaces[0]
    assert entry.occupancy(result.period_hours) > 1.0
    assert [e.furnace for e in result.overbooked()] == ["HT-04"]


def test_a_normal_week_is_not_overbooked() -> None:
    result = measure([load("L25-0001")], START, END)
    assert result.overbooked() == ()


def test_entry_text() -> None:
    result = measure([load("L25-0001")], START, END)
    assert str(result.furnaces[0]) == "HT-04: 1 load(s), 6:00 occupied"


def test_a_load_finishing_before_it_was_charged_occupies_nothing() -> None:
    backwards = load(
        "L25-0001",
        charged=datetime(2025, 5, 2, 12, 0),
        finished=datetime(2025, 5, 2, 6, 0),
    )
    assert occupied_by(backwards).seconds == pytest.approx(0.0)
