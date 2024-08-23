"""Printed views of system accuracy testing."""

from __future__ import annotations

from datetime import date

from ..report.table import Align, Column, Table, render_kv
from .evaluate import SatResult
from .schedule import SatHistory


def result_table(history: SatHistory) -> Table:
    """Every test on one furnace, oldest first."""
    table = Table(
        columns=[
            Column("test"),
            Column("date"),
            Column("setpoint", align=Align.RIGHT, places=0),
            Column("system", align=Align.RIGHT, places=1),
            Column("probe", align=Align.RIGHT, places=1),
            Column("difference", align=Align.RIGHT, places=1),
            Column("allowed", align=Align.RIGHT, places=1),
            Column("verdict"),
        ],
        title=f"system accuracy tests on {history.furnace}",
    )
    for result in history.results:
        test = result.test
        table.add(
            test.number,
            test.performed.isoformat(),
            test.setpoint.degf,
            test.system_value.degf,
            test.test_value.degf,
            result.difference.degf,
            result.tolerance.degf,
            result.verdict.value,
        )
    return table


def due_board(histories: list[SatHistory], on: date, *, grace: int = 0) -> Table:
    """The shop wide board, most overdue first."""
    table = Table(
        columns=[
            Column("furnace"),
            Column("interval"),
            Column("last pass"),
            Column("due"),
            Column("days", align=Align.RIGHT),
            Column("state"),
        ],
        title=f"system accuracy tests due as of {on.isoformat()}",
    )
    entries = [h.due(on, grace=grace) for h in histories]
    entries.sort(key=lambda e: (e.days_left is not None, e.days_left or 0, str(e.furnace)))
    for entry in entries:
        table.add(
            str(entry.furnace),
            str(entry.interval),
            entry.last_passed.isoformat() if entry.last_passed else None,
            entry.due.isoformat() if entry.due else None,
            entry.days_left,
            "never tested"
            if entry.never_tested
            else ("overdue" if entry.overdue else "in date"),
        )
    return table


def failure_notice(history: SatHistory, failure: SatResult) -> str:
    """The block that goes on a nonconformance report after a failed test."""
    window = history.failure_window(failure)
    if window is None:
        return f"{failure.test.number} passed, nothing to report"
    return render_kv(
        [
            ("furnace", str(history.furnace)),
            ("test", failure.test.number),
            ("performed", failure.test.performed.isoformat()),
            ("setpoint", failure.test.setpoint.format()),
            ("difference", failure.difference.format()),
            ("allowed", failure.tolerance.format()),
            ("work in doubt from", window[0].isoformat()),
            ("work in doubt to", window[1].isoformat()),
        ],
        title="system accuracy test failure",
    )


def history_summary(history: SatHistory, on: date) -> str:
    due = history.due(on)
    latest = history.latest()
    return render_kv(
        [
            ("furnace", str(history.furnace)),
            ("class", history.furnace_class.value),
            ("instrumentation", history.instrumentation.value),
            ("tests on file", len(history.results)),
            ("consecutive passes", history.consecutive_passes()),
            ("interval", str(due.interval)),
            ("next due", due.due.isoformat() if due.due else None),
            ("latest verdict", latest.verdict.value if latest else None),
        ],
        title="sat summary",
    )
