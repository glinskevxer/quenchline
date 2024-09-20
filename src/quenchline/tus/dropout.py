"""Sensors that stop reading part way through a survey.

Survey couples get pulled out by a rack shifting, a lead shorting on a hearth
rail, or a weld letting go at temperature. It happens often enough that a rule
that threw away every survey with a dead couple would throw away a third of
them, and often enough that a rule that ignored it would let a shop survey a
furnace with three couples and call it nine.

The rule that is actually defensible turns on **which** couple was lost, not how
many:

* the **centre** couple is never expendable. It is the one point that is not on
  a boundary and losing it means nothing is known about the middle of the zone.
* a **corner** couple is never expendable either, for the opposite reason. The
  corners are where a furnace goes wrong and a survey that lost one has lost the
  worst case it was hunting for.
* everything else is padding, and a survey may lose up to a tenth of its couples
  rounded down, so nine couples may lose none and eleven may lose one.

A couple that produced no reading at all is not a dropout. It is a couple that
was never in the survey, and the survey is short rather than damaged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..timespan import Duration
from .survey import Survey, SurveySetpoint

LOSS_FRACTION = 0.1


class DropoutVerdict(Enum):
    ACCEPTABLE = "acceptable"
    CENTRE_LOST = "centre_lost"
    CORNER_LOST = "corner_lost"
    TOO_MANY_LOST = "too_many_lost"

    @property
    def survey_stands(self) -> bool:
        return self is DropoutVerdict.ACCEPTABLE


@dataclass(frozen=True)
class Dropout:
    """One sensor that stopped reading part way through."""

    sensor: str
    last_seen: Duration
    is_corner: bool
    is_centre: bool

    @property
    def is_critical(self) -> bool:
        return self.is_corner or self.is_centre


@dataclass(frozen=True)
class DropoutReport:
    """What the survey lost, and whether it survives."""

    dropouts: tuple[Dropout, ...]
    never_read: tuple[str, ...]
    allowed: int
    verdict: DropoutVerdict

    @property
    def survey_stands(self) -> bool:
        return self.verdict.survey_stands

    @property
    def lost(self) -> int:
        return len(self.dropouts)

    def __str__(self) -> str:
        if not self.dropouts and not self.never_read:
            return "no sensors lost"
        return f"{self.lost} lost of an allowed {self.allowed}: {self.verdict.value}"


def allowed_losses(sensor_count: int) -> int:
    """How many non critical couples a survey of this size may lose."""
    if sensor_count < 1:
        raise ValidationError("a survey needs sensors", field="sensor_count")
    return int(sensor_count * LOSS_FRACTION)


def find_dropouts(survey: Survey, data: SurveySetpoint) -> DropoutReport:
    """Work out which sensors stopped reading during one set point."""
    expected = set(survey.keys)
    last_seen: dict[str, Duration] = {}
    for scan in data.scans:
        for key, _ in scan.values:
            last_seen[key] = scan.elapsed

    never_read = tuple(sorted(expected - set(last_seen)))
    finish = data.duration
    dropouts: list[Dropout] = []
    for key in sorted(last_seen):
        if key not in expected:
            continue
        if last_seen[key].seconds >= finish.seconds:
            continue
        point = survey.point(key)
        dropouts.append(Dropout(key, last_seen[key], point.is_corner, point.is_centre))

    allowed = allowed_losses(survey.sensor_count)
    verdict = _verdict(tuple(dropouts), allowed)
    return DropoutReport(tuple(dropouts), never_read, allowed, verdict)


def _verdict(dropouts: tuple[Dropout, ...], allowed: int) -> DropoutVerdict:
    if any(d.is_centre for d in dropouts):
        return DropoutVerdict.CENTRE_LOST
    if any(d.is_corner for d in dropouts):
        return DropoutVerdict.CORNER_LOST
    if len(dropouts) > allowed:
        return DropoutVerdict.TOO_MANY_LOST
    return DropoutVerdict.ACCEPTABLE


def surviving_keys(survey: Survey, report: DropoutReport) -> tuple[str, ...]:
    """The sensors whose data can still be used."""
    lost = {d.sensor for d in report.dropouts} | set(report.never_read)
    return tuple(key for key in survey.keys if key not in lost)
