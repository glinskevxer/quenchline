"""The load record.

A load is a basket of parts that went through one furnace on one cycle. It is
the unit everything else in this package is ultimately about: a survey qualifies
a furnace so that a load can run in it, a certificate is issued against a load,
and a nonconformance is raised on a load.

The record moves through states in one direction, and the transitions are where
the shop's rules bite:

    planned -> charged -> running -> complete -> certified
                                          \\-> rejected
    any of the above (except certified) -> held -> back where it was

The rule worth stating is that **certification is not a state you can reach from
running**. A load has to be complete, which means the trace is in, before
anybody can say it met the cycle. Shops that certify off the controller display
while the furnace is still hot find out about the last twenty minutes later.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum

from ..errors import StateError, ValidationError
from ..identity import FurnaceTag, LotNumber, SensorTag, WorkOrder
from ..measure import Mass
from .trace import Trace


class LoadState(Enum):
    PLANNED = "planned"
    CHARGED = "charged"
    RUNNING = "running"
    COMPLETE = "complete"
    CERTIFIED = "certified"
    REJECTED = "rejected"
    HELD = "held"

    @property
    def is_final(self) -> bool:
        return self in {LoadState.CERTIFIED, LoadState.REJECTED}

    @property
    def is_in_furnace(self) -> bool:
        return self in {LoadState.CHARGED, LoadState.RUNNING}


@dataclass(frozen=True)
class PartLine:
    """One part number on the load."""

    part_number: str
    quantity: int
    material: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.part_number.strip():
            raise ValidationError("a part line needs a part number", field="part_number")
        if self.quantity < 1:
            raise ValidationError("a part line needs a quantity", field="quantity")


@dataclass(frozen=True)
class Load:
    """One charge through one furnace."""

    lot: LotNumber
    work_order: WorkOrder
    furnace: FurnaceTag
    recipe_code: str
    recipe_revision: str
    parts: tuple[PartLine, ...] = field(default_factory=tuple)
    weight: Mass | None = None
    load_sensors: tuple[SensorTag, ...] = field(default_factory=tuple)
    state: LoadState = LoadState.PLANNED
    charged_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    trace: Trace | None = None
    trace_source: str = ""
    trace_digest: str = ""
    trace_profile: str = ""
    previous_state: LoadState | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.recipe_code.strip():
            raise ValidationError("a load needs a recipe code", field="recipe_code")
        if not self.recipe_revision.strip():
            raise ValidationError("a load needs a recipe revision", field="recipe_revision")
        tags = [str(t) for t in self.load_sensors]
        if len(set(tags)) != len(tags):
            raise ValidationError("the same load sensor is fitted twice", field="load_sensors")

    @property
    def piece_count(self) -> int:
        return sum(line.quantity for line in self.parts)

    @property
    def recipe(self) -> str:
        return f"{self.recipe_code} rev {self.recipe_revision}"

    @property
    def has_trace(self) -> bool:
        return self.trace is not None

    @property
    def has_trace_reference(self) -> bool:
        """Whether a logger file has been recorded against this load.

        The trace itself lives in the file it arrived as, so a load read back
        from the database carries the reference and not the readings.
        """
        return self.trace is not None or bool(self.trace_source or self.trace_digest)

    def trace_or_raise(self) -> Trace:
        if self.trace is None:
            raise StateError(f"load {self.lot} has no trace", state=self.state.value)
        return self.trace

    def _require(self, *states: LoadState) -> None:
        if self.state not in states:
            allowed = ", ".join(s.value for s in states)
            raise StateError(
                f"a load in {self.state.value} cannot do that, it must be {allowed}",
                state=self.state.value,
            )

    def charge(self, at: datetime, sensors: tuple[SensorTag, ...] = ()) -> Load:
        self._require(LoadState.PLANNED)
        return replace(
            self,
            state=LoadState.CHARGED,
            charged_at=at,
            load_sensors=sensors or self.load_sensors,
        )

    def start(self, at: datetime) -> Load:
        self._require(LoadState.CHARGED)
        if self.charged_at is not None and at < self.charged_at:
            raise ValidationError("a load cannot start before it was charged", field="at")
        return replace(self, state=LoadState.RUNNING, started_at=at)

    def attach(self, trace: Trace, *, digest: str = "") -> Load:
        """Hang a trace on the load, wherever it is in its life.

        The trace is attached before the load is finished, not as part of
        finishing it, because the logger file usually lands minutes after the
        furnace door opens and somebody has to be able to look at it before
        deciding the load is done.
        """
        if self.state.is_final:
            raise StateError("a finished load cannot take a new trace", state=self.state.value)
        return replace(self, trace=trace, trace_source=trace.source, trace_digest=digest)

    def with_profile(self, profile: str) -> Load:
        """Remember which mapping profile read the attached file.

        Without it, grading a load a month later means guessing which logger
        wrote the file, and guessing wrong reads Celsius as Fahrenheit.
        """
        return replace(self, trace_profile=profile)

    def finish(self, at: datetime) -> Load:
        """Close the cycle. The trace has to be on the load already.

        Finishing used to take the trace as an argument, which quietly allowed a
        load to be closed with a trace nobody had recorded anywhere. The trace
        is attached first, by name, and finishing checks it is there.
        """
        self._require(LoadState.RUNNING)
        if not self.has_trace_reference:
            raise StateError(
                "attach the logger file before finishing the load", state=self.state.value
            )
        if self.started_at is not None and at < self.started_at:
            raise ValidationError("a load cannot finish before it started", field="at")
        return replace(self, state=LoadState.COMPLETE, finished_at=at)

    def certify(self) -> Load:
        self._require(LoadState.COMPLETE)
        if not self.has_trace_reference:
            raise StateError("a load with no trace cannot be certified", state=self.state.value)
        return replace(self, state=LoadState.CERTIFIED)

    def reject(self, reason: str) -> Load:
        self._require(LoadState.COMPLETE, LoadState.HELD)
        if not reason.strip():
            raise ValidationError("give a reason", field="reason")
        return replace(self, state=LoadState.REJECTED, notes=(*self.notes, reason))

    def hold(self, reason: str) -> Load:
        if self.state.is_final:
            raise StateError("a finished load cannot be put on hold", state=self.state.value)
        if self.state is LoadState.HELD:
            raise StateError("this load is already on hold", state="held")
        if not reason.strip():
            raise ValidationError("give a reason", field="reason")
        return replace(
            self,
            state=LoadState.HELD,
            previous_state=self.state,
            notes=(*self.notes, reason),
        )

    def release(self) -> Load:
        if self.state is not LoadState.HELD:
            raise StateError("only a held load can be released", state=self.state.value)
        assert self.previous_state is not None
        return replace(self, state=self.previous_state, previous_state=None)

    def __str__(self) -> str:
        return f"{self.lot} on {self.furnace} to {self.recipe}"
