"""Where the work actually went.

Utilisation in a heat treat shop is not machine hours. Nobody meters the
furnaces, and the number that matters to a scheduler is not how long a furnace
was hot but **how many loads it took and how much of the week it was occupied**,
because a furnace occupied by a twelve hour temper is unavailable whether it is
drawing power or not.

So occupancy is measured from the load record: charged to finished, summed per
furnace, against the length of the period. That produces a number over one when
two loads overlap on the same furnace, which is not an error. It means somebody
double booked, and the report says so rather than quietly clamping it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from ..errors import ValidationError
from ..loads.record import Load, LoadState
from ..timespan import Duration

HOURS_PER_DAY = 24.0


@dataclass(frozen=True)
class FurnaceLoad:
    """One furnace's share of a period."""

    furnace: str
    loads: int
    pieces: int
    occupied: Duration
    certified: int
    rejected: int

    @property
    def finished(self) -> int:
        return self.certified + self.rejected

    def occupancy(self, period_hours: float) -> float:
        if period_hours <= 0:
            raise ValidationError("the period has no length", field="period")
        return self.occupied.hours / period_hours

    def __str__(self) -> str:
        return f"{self.furnace}: {self.loads} load(s), {self.occupied.format()} occupied"


@dataclass(frozen=True)
class Workload:
    """Every furnace's share of one period."""

    start: date
    end: date
    furnaces: tuple[FurnaceLoad, ...]

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValidationError("the period runs backwards", field="period")

    @property
    def period_hours(self) -> float:
        return ((self.end - self.start).days + 1) * HOURS_PER_DAY

    @property
    def total_loads(self) -> int:
        return sum(entry.loads for entry in self.furnaces)

    @property
    def busiest(self) -> FurnaceLoad | None:
        if not self.furnaces:
            return None
        return max(self.furnaces, key=lambda entry: entry.occupied.seconds)

    @property
    def quietest(self) -> FurnaceLoad | None:
        if not self.furnaces:
            return None
        return min(self.furnaces, key=lambda entry: entry.occupied.seconds)

    def overbooked(self) -> tuple[FurnaceLoad, ...]:
        """Furnaces whose loads add up to more time than the period holds."""
        return tuple(
            entry for entry in self.furnaces if entry.occupancy(self.period_hours) > 1.0
        )

    def for_furnace(self, tag: str) -> FurnaceLoad | None:
        for entry in self.furnaces:
            if entry.furnace == tag:
                return entry
        return None


def occupied_by(load: Load) -> Duration:
    """How long one load held its furnace.

    Charged to finished, because a load sitting in a cold furnace waiting for
    the operator still occupies it. A load that never finished contributes
    nothing, because nobody knows yet how long it will take.
    """
    if load.charged_at is None or load.finished_at is None:
        return Duration(0.0)
    seconds = (load.finished_at - load.charged_at).total_seconds()
    return Duration(max(0.0, seconds))


def measure(loads: list[Load], start: date, end: date) -> Workload:
    """Roll a list of loads up per furnace over a period."""
    if end < start:
        raise ValidationError("the period runs backwards", field="period")
    window_start = datetime.combine(start, time.min)
    window_end = datetime.combine(end, time.max)

    grouped: dict[str, list[Load]] = {}
    for load in loads:
        if load.finished_at is None:
            continue
        if not window_start <= load.finished_at <= window_end:
            continue
        grouped.setdefault(str(load.furnace), []).append(load)

    entries: list[FurnaceLoad] = []
    for tag in sorted(grouped):
        records = grouped[tag]
        entries.append(
            FurnaceLoad(
                furnace=tag,
                loads=len(records),
                pieces=sum(record.piece_count for record in records),
                occupied=Duration(sum(occupied_by(record).seconds for record in records)),
                certified=sum(1 for record in records if record.state is LoadState.CERTIFIED),
                rejected=sum(1 for record in records if record.state is LoadState.REJECTED),
            )
        )
    return Workload(start, end, tuple(entries))
