"""The numbers the shop is measured on.

Four of them, and they are chosen because each one moves for a reason somebody
can act on.

**Throughput** is loads and pieces put through. It is the only one that goes up.

**First pass yield** is the share of finished loads that were certified without
a rework or a concession. A shop can raise its certified share by accepting
everything under concession, so the concession count is reported next to it and
not buried.

**Deviation rate** is findings per finished load. It rises before yield falls,
which is what makes it worth watching.

**Furnace utilisation** is loads per furnace, and it is here because it is what
tells you whether a survey slipping on one furnace actually cost anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..errors import ValidationError
from ..loads.disposition import Disposition
from ..loads.record import Load, LoadState
from .table import Align, Column, Table, render_kv


@dataclass(frozen=True)
class Period:
    """The window a rollup covers."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValidationError("a period must run forward", field="period")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def __str__(self) -> str:
        return f"{self.start.isoformat()} to {self.end.isoformat()}"


@dataclass(frozen=True)
class Rollup:
    """The four numbers, plus what they were worked out from."""

    period: Period
    loads: int
    pieces: int
    certified: int
    rejected: int
    concessions: int
    deviations: int
    furnaces: int

    @property
    def finished(self) -> int:
        return self.certified + self.rejected

    @property
    def first_pass_yield(self) -> float | None:
        if self.finished == 0:
            return None
        clean = self.certified - self.concessions
        return max(0.0, clean) / self.finished

    @property
    def certified_share(self) -> float | None:
        if self.finished == 0:
            return None
        return self.certified / self.finished

    @property
    def deviation_rate(self) -> float | None:
        if self.finished == 0:
            return None
        return self.deviations / self.finished

    @property
    def loads_per_furnace(self) -> float | None:
        if self.furnaces == 0:
            return None
        return self.loads / self.furnaces

    @property
    def loads_per_day(self) -> float:
        return self.loads / self.period.days


def rollup(
    loads: list[Load],
    period: Period,
    *,
    dispositions: dict[str, Disposition] | None = None,
    deviations: dict[str, int] | None = None,
    furnace_count: int = 0,
) -> Rollup:
    """Roll a list of loads up into the four numbers."""
    dispositions = dispositions or {}
    deviations = deviations or {}

    inside = [
        item
        for item in loads
        if item.finished_at is not None and period.contains(item.finished_at.date())
    ]
    certified = sum(1 for item in inside if item.state is LoadState.CERTIFIED)
    rejected = sum(1 for item in inside if item.state is LoadState.REJECTED)
    concessions = sum(
        1 for item in inside if dispositions.get(str(item.lot)) is Disposition.ACCEPT_AS_IS
    )
    found = sum(deviations.get(str(item.lot), 0) for item in inside)
    return Rollup(
        period=period,
        loads=len(inside),
        pieces=sum(item.piece_count for item in inside),
        certified=certified,
        rejected=rejected,
        concessions=concessions,
        deviations=found,
        furnaces=furnace_count,
    )


def rollup_block(result: Rollup) -> str:
    return render_kv(
        [
            ("period", str(result.period)),
            ("loads", result.loads),
            ("pieces", result.pieces),
            ("certified", result.certified),
            ("rejected", result.rejected),
            ("concessions", result.concessions),
            ("first pass yield", _percent(result.first_pass_yield)),
            ("certified share", _percent(result.certified_share)),
            ("deviations per load", _rate(result.deviation_rate)),
            ("loads per furnace", _rate(result.loads_per_furnace)),
            ("loads per day", f"{result.loads_per_day:.2f}"),
        ],
        title="shop performance",
    )


def comparison_table(current: Rollup, previous: Rollup) -> Table:
    """This period against the last one, for a management pack."""
    table = Table(
        columns=[
            Column("measure"),
            Column("previous", align=Align.RIGHT),
            Column("current", align=Align.RIGHT),
            Column("direction", align=Align.CENTRE),
        ],
        title="period on period",
    )
    rows: list[tuple[str, float | None, float | None]] = [
        ("loads", float(previous.loads), float(current.loads)),
        ("pieces", float(previous.pieces), float(current.pieces)),
        ("first pass yield", previous.first_pass_yield, current.first_pass_yield),
        ("deviations per load", previous.deviation_rate, current.deviation_rate),
    ]
    for name, was, now in rows:
        table.add(name, _number(was), _number(now), _direction(was, now))
    return table


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f} percent"


def _rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _direction(was: float | None, now: float | None) -> str:
    if was is None or now is None:
        return "-"
    if abs(now - was) < 1e-9:
        return "flat"
    return "up" if now > was else "down"
