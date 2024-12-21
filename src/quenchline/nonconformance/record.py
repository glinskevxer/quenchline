"""The nonconformance report.

An NCR is raised when something in the shop did not go the way the paperwork
says it should. It is not only about metal: a failed system accuracy test, an
instrument found out of calibration and a survey that could not be completed all
raise one, and all three are about equipment rather than parts.

The lifecycle has one thing worth designing carefully, which is that **closing
an NCR is not one step**. A finding gets a disposition, then the disposition
gets carried out, and only then is the thing closed. Shops that collapse those
into one step end up with a pile of NCRs marked "reworked" where nobody reran
the cycle.

The other rule that earns its keep: an NCR against equipment has to name what it
throws into doubt. A failed SAT that closes without a back-check on the loads
run since the last passing test has not been dealt with, it has been filed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum

from ..errors import StateError, ValidationError
from ..loads.disposition import Disposition


class NcrSubject(Enum):
    """What the report is about."""

    LOAD = "load"
    FURNACE = "furnace"
    INSTRUMENT = "instrument"
    SENSOR = "sensor"
    BATH = "bath"
    SURVEY = "survey"

    @property
    def is_equipment(self) -> bool:
        return self is not NcrSubject.LOAD

    @property
    def can_hold_work_back(self) -> bool:
        """Whether a finding here throws earlier work into doubt."""
        return self in {NcrSubject.INSTRUMENT, NcrSubject.SENSOR, NcrSubject.FURNACE}


class NcrStage(Enum):
    RAISED = "raised"
    DISPOSITIONED = "dispositioned"
    ACTIONED = "actioned"
    CLOSED = "closed"
    VOIDED = "voided"

    @property
    def is_open(self) -> bool:
        return self in {NcrStage.RAISED, NcrStage.DISPOSITIONED, NcrStage.ACTIONED}

    @property
    def is_final(self) -> bool:
        return self in {NcrStage.CLOSED, NcrStage.VOIDED}


@dataclass(frozen=True)
class Nonconformance:
    """One nonconformance report."""

    number: str
    subject: NcrSubject
    reference: str
    raised_on: date
    summary: str
    stage: NcrStage = NcrStage.RAISED
    disposition: Disposition | None = None
    disposition_on: date | None = None
    actioned_on: date | None = None
    closed_on: date | None = None
    suspect_from: date | None = None
    suspect_to: date | None = None
    raised_by: str = ""
    entries: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("an ncr needs a number", field="number")
        if not self.reference.strip():
            raise ValidationError("an ncr needs a subject reference", field="reference")
        if not self.summary.strip():
            raise ValidationError("an ncr needs a summary", field="summary")
        if (self.suspect_from is None) != (self.suspect_to is None):
            raise ValidationError("a suspect window needs both ends", field="suspect")
        backwards = (
            self.suspect_from is not None
            and self.suspect_to is not None
            and self.suspect_to < self.suspect_from
        )
        if backwards:
            raise ValidationError("the suspect window runs backwards", field="suspect")

    @property
    def is_open(self) -> bool:
        return self.stage.is_open

    @property
    def has_suspect_window(self) -> bool:
        return self.suspect_from is not None

    def with_suspect_window(self, start: date, end: date) -> Nonconformance:
        return replace(self, suspect_from=start, suspect_to=end)

    def note(self, text: str) -> Nonconformance:
        if not text.strip():
            raise ValidationError("an entry needs text", field="text")
        return replace(self, entries=(*self.entries, text.strip()))

    def _require(self, *stages: NcrStage) -> None:
        if self.stage not in stages:
            allowed = ", ".join(s.value for s in stages)
            raise StateError(
                f"an ncr at {self.stage.value} cannot do that, it must be {allowed}",
                state=self.stage.value,
            )

    def disposition_as(self, disposition: Disposition, on: date) -> Nonconformance:
        self._require(NcrStage.RAISED)
        if on < self.raised_on:
            raise ValidationError("a disposition cannot predate the report", field="on")
        return replace(
            self,
            stage=NcrStage.DISPOSITIONED,
            disposition=disposition,
            disposition_on=on,
        )

    def action(self, on: date, note: str) -> Nonconformance:
        self._require(NcrStage.DISPOSITIONED)
        if not note.strip():
            raise ValidationError("say what was done", field="note")
        if self.disposition_on is not None and on < self.disposition_on:
            raise ValidationError("an action cannot predate the disposition", field="on")
        return replace(
            self,
            stage=NcrStage.ACTIONED,
            actioned_on=on,
            entries=(*self.entries, note.strip()),
        )

    def close(self, on: date) -> Nonconformance:
        self._require(NcrStage.ACTIONED)
        if self.subject.can_hold_work_back and not self.has_suspect_window:
            raise StateError(
                "an equipment ncr cannot close without saying what it throws into doubt",
                state=self.stage.value,
            )
        if self.actioned_on is not None and on < self.actioned_on:
            raise ValidationError("a closure cannot predate the action", field="on")
        return replace(self, stage=NcrStage.CLOSED, closed_on=on)

    def void(self, reason: str) -> Nonconformance:
        if self.stage.is_final:
            raise StateError("this ncr is already finished", state=self.stage.value)
        if not reason.strip():
            raise ValidationError("give a reason", field="reason")
        return replace(self, stage=NcrStage.VOIDED, entries=(*self.entries, reason.strip()))

    def age(self, on: date) -> int:
        return (on - self.raised_on).days

    def __str__(self) -> str:
        return f"{self.number} {self.subject.value} {self.reference} ({self.stage.value})"
