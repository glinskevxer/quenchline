from __future__ import annotations

from datetime import datetime

import pytest

from quenchline.errors import StateError, ValidationError
from quenchline.identity import FurnaceTag, LotNumber, SensorTag, WorkOrder
from quenchline.loads.record import Load, LoadState, PartLine
from quenchline.loads.trace import Channel, ChannelRole, Trace
from quenchline.measure import Mass
from quenchline.timespan import minutes

CHARGED = datetime(2024, 11, 4, 6, 30)
STARTED = datetime(2024, 11, 4, 7, 0)
FINISHED = datetime(2024, 11, 4, 12, 0)

TRACE = Trace(
    STARTED,
    (
        Channel.of(
            "C1",
            ChannelRole.CONTROL,
            [(minutes(0), 100.0), (minutes(300), 1550.0)],
        ),
    ),
)


def load(**changes: object) -> Load:
    base: dict[str, object] = {
        "lot": LotNumber.parse("L24-0917"),
        "work_order": WorkOrder.parse("W104417"),
        "furnace": FurnaceTag.parse("HT-04"),
        "recipe_code": "HT-4140-Q",
        "recipe_revision": "C",
        "parts": (PartLine("PN-8891", 40, "4140"), PartLine("PN-8892", 12, "4140")),
        "weight": Mass.pounds(1450),
    }
    base.update(changes)
    return Load(**base)  # type: ignore[arg-type]


def test_state_groups() -> None:
    assert LoadState.CERTIFIED.is_final
    assert LoadState.REJECTED.is_final
    assert not LoadState.COMPLETE.is_final
    assert LoadState.CHARGED.is_in_furnace
    assert LoadState.RUNNING.is_in_furnace
    assert not LoadState.PLANNED.is_in_furnace


def test_part_line_validation() -> None:
    with pytest.raises(ValidationError):
        PartLine("  ", 1)
    with pytest.raises(ValidationError):
        PartLine("PN-1", 0)


def test_a_load_starts_planned_and_counts_its_pieces() -> None:
    item = load()
    assert item.state is LoadState.PLANNED
    assert item.piece_count == 52
    assert item.recipe == "HT-4140-Q rev C"
    assert str(item) == "L24-0917 on HT-04 to HT-4140-Q rev C"


def test_a_load_needs_a_recipe() -> None:
    with pytest.raises(ValidationError):
        load(recipe_code=" ")
    with pytest.raises(ValidationError):
        load(recipe_revision="")


def test_the_same_load_sensor_cannot_be_fitted_twice() -> None:
    with pytest.raises(ValidationError):
        load(load_sensors=(SensorTag.parse("TC-01"), SensorTag.parse("TC-01")))


def test_the_happy_path() -> None:
    item = load()
    item = item.charge(CHARGED, (SensorTag.parse("TC-01"),))
    assert item.state is LoadState.CHARGED
    assert item.load_sensors[0].serial == 1
    item = item.start(STARTED)
    assert item.state is LoadState.RUNNING
    item = item.finish(FINISHED, TRACE)
    assert item.state is LoadState.COMPLETE
    assert item.has_trace
    item = item.certify()
    assert item.state is LoadState.CERTIFIED


def test_states_cannot_be_skipped() -> None:
    item = load()
    with pytest.raises(StateError):
        item.start(STARTED)
    with pytest.raises(StateError):
        item.finish(FINISHED, TRACE)
    with pytest.raises(StateError):
        item.certify()


def test_a_running_load_cannot_be_certified() -> None:
    item = load().charge(CHARGED).start(STARTED)
    with pytest.raises(StateError):
        item.certify()


def test_a_load_with_no_trace_cannot_be_certified() -> None:
    item = load(state=LoadState.COMPLETE)
    assert not item.has_trace
    with pytest.raises(StateError):
        item.certify()
    with pytest.raises(StateError):
        item.trace_or_raise()


def test_times_must_run_forward() -> None:
    item = load().charge(CHARGED)
    with pytest.raises(ValidationError):
        item.start(datetime(2024, 11, 4, 5, 0))
    running = item.start(STARTED)
    with pytest.raises(ValidationError):
        running.finish(datetime(2024, 11, 4, 6, 45), TRACE)


def test_rejection_needs_a_reason_and_is_final() -> None:
    item = load().charge(CHARGED).start(STARTED).finish(FINISHED, TRACE)
    with pytest.raises(ValidationError):
        item.reject("  ")
    rejected = item.reject("soak short by twelve minutes")
    assert rejected.state is LoadState.REJECTED
    assert "soak short by twelve minutes" in rejected.notes
    with pytest.raises(StateError):
        rejected.certify()


def test_a_hold_remembers_where_it_came_from() -> None:
    item = load().charge(CHARGED).start(STARTED)
    held = item.hold("furnace survey overdue")
    assert held.state is LoadState.HELD
    assert held.previous_state is LoadState.RUNNING
    released = held.release()
    assert released.state is LoadState.RUNNING
    assert released.previous_state is None


def test_a_hold_needs_a_reason_and_cannot_be_doubled() -> None:
    item = load().charge(CHARGED)
    with pytest.raises(ValidationError):
        item.hold("   ")
    held = item.hold("paperwork")
    with pytest.raises(StateError):
        held.hold("more paperwork")


def test_a_finished_load_cannot_be_held() -> None:
    item = load().charge(CHARGED).start(STARTED).finish(FINISHED, TRACE).certify()
    with pytest.raises(StateError):
        item.hold("too late")


def test_only_a_held_load_can_be_released() -> None:
    with pytest.raises(StateError):
        load().release()


def test_a_held_load_can_be_rejected_without_being_released_first() -> None:
    item = load().charge(CHARGED).start(STARTED).finish(FINISHED, TRACE)
    held = item.hold("waiting on hardness")
    assert held.reject("hardness low").state is LoadState.REJECTED


def test_transitions_do_not_mutate_the_original() -> None:
    item = load()
    charged = item.charge(CHARGED)
    assert item.state is LoadState.PLANNED
    assert charged is not item
