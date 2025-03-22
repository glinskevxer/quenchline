"""The compliance summary a customer audit asks for.

An auditor does not want the register. They want the answer to a short list of
questions, each of which is either satisfied or is not, with the exceptions
named underneath. So this reduces the whole shop to a list of findings, and each
finding is a criterion plus the things that failed it.

The criteria are deliberately few. A summary with forty lines is a register with
a different heading, and the point of a summary is that somebody reads all of
it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..nonconformance.record import Nonconformance
from ..schedule.board import Board
from ..schedule.policy import Activity
from .table import Align, Column, Table, render_kv


class Criterion(Enum):
    """The questions an audit asks."""

    SURVEYS_IN_DATE = "surveys in date"
    ACCURACY_TESTS_IN_DATE = "system accuracy tests in date"
    INSTRUMENTS_CALIBRATED = "instruments calibrated"
    SENSORS_CALIBRATED = "sensors calibrated"
    BATHS_CHECKED = "quench baths checked"
    NO_OVERDUE_NONCONFORMANCE = "no nonconformance older than the limit"

    @property
    def activity(self) -> Activity | None:
        mapping = {
            Criterion.SURVEYS_IN_DATE: Activity.UNIFORMITY_SURVEY,
            Criterion.ACCURACY_TESTS_IN_DATE: Activity.SYSTEM_ACCURACY_TEST,
            Criterion.INSTRUMENTS_CALIBRATED: Activity.INSTRUMENT_CALIBRATION,
            Criterion.SENSORS_CALIBRATED: Activity.SENSOR_CALIBRATION,
            Criterion.BATHS_CHECKED: Activity.BATH_CHECK,
        }
        return mapping.get(self)


@dataclass(frozen=True)
class Finding:
    """One criterion and whatever failed it."""

    criterion: Criterion
    satisfied: bool
    exceptions: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.exceptions)

    def __str__(self) -> str:
        if self.satisfied:
            return f"{self.criterion.value}: satisfied"
        return f"{self.criterion.value}: {self.count} exception(s)"


@dataclass(frozen=True)
class ComplianceSummary:
    """The whole shop reduced to a handful of answers."""

    on: date
    findings: tuple[Finding, ...]

    @property
    def satisfied(self) -> bool:
        return all(finding.satisfied for finding in self.findings)

    @property
    def failures(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if not f.satisfied)

    @property
    def exception_count(self) -> int:
        return sum(f.count for f in self.findings)

    def finding(self, criterion: Criterion) -> Finding:
        for candidate in self.findings:
            if candidate.criterion is criterion:
                return candidate
        raise KeyError(criterion)


NCR_AGE_LIMIT = 90


def assess(
    board: Board,
    reports: list[Nonconformance],
    on: date,
    *,
    ncr_age_limit: int = NCR_AGE_LIMIT,
) -> ComplianceSummary:
    """Reduce a schedule board and an ncr register to a compliance summary."""
    findings: list[Finding] = []
    for criterion in Criterion:
        activity = criterion.activity
        if activity is None:
            continue
        late = [item.subject for item in board.of(activity) if item.urgency.needs_attention]
        findings.append(Finding(criterion, not late, tuple(sorted(late))))

    stale = [
        report.number for report in reports if report.is_open and report.age(on) > ncr_age_limit
    ]
    findings.append(
        Finding(Criterion.NO_OVERDUE_NONCONFORMANCE, not stale, tuple(sorted(stale)))
    )
    return ComplianceSummary(on, tuple(findings))


def summary_table(summary: ComplianceSummary) -> Table:
    table = Table(
        columns=[
            Column("criterion"),
            Column("result"),
            Column("exceptions", align=Align.RIGHT),
            Column("detail"),
        ],
        title=f"compliance summary as of {summary.on.isoformat()}",
    )
    for finding in summary.findings:
        table.add(
            finding.criterion.value,
            "satisfied" if finding.satisfied else "exception",
            finding.count,
            ", ".join(finding.exceptions) if finding.exceptions else None,
        )
    return table


def summary_header(summary: ComplianceSummary) -> str:
    return render_kv(
        [
            ("as of", summary.on.isoformat()),
            ("criteria", len(summary.findings)),
            ("satisfied", len(summary.findings) - len(summary.failures)),
            ("exceptions", summary.exception_count),
            ("overall", "satisfied" if summary.satisfied else "exception"),
        ],
        title="compliance",
    )
