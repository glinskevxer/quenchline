"""Building the shop board out of the registers that actually hold the dates.

Every register in this package already knows when its own things come due. This
module asks them, one at a time, and turns the answers into the common
:class:`~quenchline.schedule.policy.DueItem` shape.

Nothing here recomputes a due date. If the survey interval changes, this file
does not change, and that is the point: there is exactly one implementation of
each rule and this is not it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..instruments.register import InstrumentRegister
from ..quench.bath import Bath
from ..report.table import Align, Column, Table, render_kv
from ..sat.schedule import SatHistory
from ..sensors.register import SensorRegister, calibration_interval
from ..tus.history import SurveyHistory
from .policy import Activity, DueItem, attention, rank


def instrument_items(
    register: InstrumentRegister, on: date, *, grace: int = 0
) -> list[DueItem]:
    items: list[DueItem] = []
    for entry in register.schedule(on, grace=grace):
        items.append(
            DueItem.of(
                Activity.INSTRUMENT_CALIBRATION,
                str(entry.instrument.tag),
                entry.due,
                on,
                grace=grace,
                detail=entry.instrument.function.value,
            )
        )
    return items


def sensor_items(register: SensorRegister, on: date, *, grace: int = 0) -> list[DueItem]:
    items: list[DueItem] = []
    for couple in register.all():
        certificate = couple.certificate
        due = (
            certificate.expires(calibration_interval(couple))
            if certificate is not None
            else None
        )
        items.append(
            DueItem.of(
                Activity.SENSOR_CALIBRATION,
                str(couple.tag),
                due,
                on,
                grace=grace,
                detail=couple.role.value,
            )
        )
    return items


def sat_items(histories: list[SatHistory], on: date, *, grace: int = 0) -> list[DueItem]:
    items: list[DueItem] = []
    for history in histories:
        entry = history.due(on, grace=grace)
        items.append(
            DueItem.of(
                Activity.SYSTEM_ACCURACY_TEST,
                str(entry.furnace),
                entry.due,
                on,
                grace=grace,
                detail=f"every {entry.interval}",
            )
        )
    return items


def survey_items(histories: list[SurveyHistory], on: date, *, grace: int = 0) -> list[DueItem]:
    items: list[DueItem] = []
    for history in histories:
        entry = history.due(on, grace=grace)
        items.append(
            DueItem.of(
                Activity.UNIFORMITY_SURVEY,
                f"{entry.furnace} {entry.zone}",
                entry.due,
                on,
                grace=grace,
                detail=f"every {entry.interval}",
            )
        )
    return items


def bath_items(baths: list[Bath], on: date, *, grace: int = 0) -> list[DueItem]:
    return [
        DueItem.of(
            Activity.BATH_CHECK,
            bath.identifier,
            bath.check_due(),
            on,
            grace=grace,
            detail=bath.medium.name,
        )
        for bath in baths
    ]


@dataclass
class Board:
    """Everything the shop owes, from every register."""

    items: list[DueItem]

    @classmethod
    def build(
        cls,
        on: date,
        *,
        instruments: InstrumentRegister | None = None,
        sensors: SensorRegister | None = None,
        sat: list[SatHistory] | None = None,
        surveys: list[SurveyHistory] | None = None,
        baths: list[Bath] | None = None,
        grace: int = 0,
    ) -> Board:
        items: list[DueItem] = []
        if instruments is not None:
            items.extend(instrument_items(instruments, on, grace=grace))
        if sensors is not None:
            items.extend(sensor_items(sensors, on, grace=grace))
        if sat is not None:
            items.extend(sat_items(sat, on, grace=grace))
        if surveys is not None:
            items.extend(survey_items(surveys, on, grace=grace))
        if baths is not None:
            items.extend(bath_items(baths, on, grace=grace))
        return cls(rank(items))

    def __len__(self) -> int:
        return len(self.items)

    def needing_attention(self) -> list[DueItem]:
        return attention(self.items)

    def of(self, activity: Activity) -> list[DueItem]:
        return [item for item in self.items if item.activity is activity]

    def blocking_furnaces(self) -> list[DueItem]:
        return [item for item in self.needing_attention() if item.activity.stops_the_furnace]


def board_table(board: Board, on: date) -> Table:
    table = Table(
        columns=[
            Column("activity"),
            Column("subject"),
            Column("due"),
            Column("days", align=Align.RIGHT),
            Column("urgency"),
            Column("detail"),
        ],
        title=f"shop schedule as of {on.isoformat()}",
    )
    for item in board.items:
        table.add(
            item.activity.value,
            item.subject,
            item.due.isoformat() if item.due else None,
            item.days_left,
            item.urgency.value,
            item.detail or None,
        )
    return table


def board_summary(board: Board, on: date) -> str:
    needing = board.needing_attention()
    return render_kv(
        [
            ("as of", on.isoformat()),
            ("items", len(board)),
            ("needing attention", len(needing)),
            ("stopping furnaces", len(board.blocking_furnaces())),
            ("worst", str(needing[0]) if needing else None),
        ],
        title="schedule summary",
    )
