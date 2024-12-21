"""The nonconformance register and the views the shop runs off it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..errors import ConflictError, NotFoundError
from ..report.table import Align, Column, Table, render_kv
from .record import NcrStage, NcrSubject, Nonconformance

AGEING_BANDS = (7, 30, 90)


@dataclass
class NcrRegister:
    """Every nonconformance report in the shop."""

    reports: dict[str, Nonconformance] = field(default_factory=dict)

    def raise_report(self, report: Nonconformance) -> None:
        if report.number in self.reports:
            raise ConflictError("nonconformance", report.number)
        self.reports[report.number] = report

    def get(self, number: str) -> Nonconformance:
        if number not in self.reports:
            raise NotFoundError("nonconformance", number)
        return self.reports[number]

    def update(self, report: Nonconformance) -> None:
        if report.number not in self.reports:
            raise NotFoundError("nonconformance", report.number)
        self.reports[report.number] = report

    def __len__(self) -> int:
        return len(self.reports)

    def __contains__(self, number: object) -> bool:
        return str(number) in self.reports

    def all(self) -> list[Nonconformance]:
        return [self.reports[key] for key in sorted(self.reports)]

    def open_reports(self) -> list[Nonconformance]:
        return [r for r in self.all() if r.is_open]

    def about(self, subject: NcrSubject) -> list[Nonconformance]:
        return [r for r in self.all() if r.subject is subject]

    def against(self, reference: str) -> list[Nonconformance]:
        return [r for r in self.all() if r.reference == reference]

    def at_stage(self, stage: NcrStage) -> list[Nonconformance]:
        return [r for r in self.all() if r.stage is stage]

    def older_than(self, days: int, on: date) -> list[Nonconformance]:
        return [r for r in self.open_reports() if r.age(on) > days]

    def ageing(self, on: date) -> dict[str, int]:
        """Open reports bucketed by how long they have been open."""
        buckets = {f"over {days} days": 0 for days in AGEING_BANDS}
        buckets["under 7 days"] = 0
        for report in self.open_reports():
            age = report.age(on)
            placed = False
            for days in sorted(AGEING_BANDS, reverse=True):
                if age > days:
                    buckets[f"over {days} days"] += 1
                    placed = True
                    break
            if not placed:
                buckets["under 7 days"] += 1
        return buckets

    def suspect_windows(self) -> list[tuple[str, date, date]]:
        out: list[tuple[str, date, date]] = []
        for report in self.all():
            if report.suspect_from is not None and report.suspect_to is not None:
                out.append((report.number, report.suspect_from, report.suspect_to))
        return out


def register_table(register: NcrRegister, on: date) -> Table:
    table = Table(
        columns=[
            Column("number"),
            Column("subject"),
            Column("reference"),
            Column("raised"),
            Column("age", align=Align.RIGHT),
            Column("stage"),
            Column("disposition"),
            Column("summary"),
        ],
        title="nonconformance register",
    )
    for report in register.all():
        table.add(
            report.number,
            report.subject.value,
            report.reference,
            report.raised_on.isoformat(),
            report.age(on),
            report.stage.value,
            report.disposition.value if report.disposition is not None else None,
            report.summary,
        )
    return table


def ageing_summary(register: NcrRegister, on: date) -> str:
    buckets = register.ageing(on)
    rows: list[tuple[str, object]] = [
        ("as of", on.isoformat()),
        ("reports", len(register)),
        ("open", len(register.open_reports())),
        ("under 7 days", buckets["under 7 days"]),
    ]
    for days in AGEING_BANDS:
        rows.append((f"over {days} days", buckets[f"over {days} days"]))
    return render_kv(rows, title="nonconformance ageing")
