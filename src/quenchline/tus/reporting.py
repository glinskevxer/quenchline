"""Printed views of uniformity surveys."""

from __future__ import annotations

from datetime import date

from ..report.table import Align, Column, Table, render_kv
from .dropout import DropoutReport
from .evaluate import SurveyResult
from .history import SurveyHistory


def setpoint_table(result: SurveyResult) -> Table:
    """One row per set point of one survey."""
    table = Table(
        columns=[
            Column("setpoint", align=Align.RIGHT, places=0),
            Column("soak"),
            Column("high", align=Align.RIGHT, places=1),
            Column("low", align=Align.RIGHT, places=1),
            Column("spread", align=Align.RIGHT, places=1),
            Column("band", align=Align.RIGHT, places=0),
            Column("verdict"),
            Column("reasons"),
        ],
        title=f"uniformity survey {result.survey.number}",
    )
    for entry in result.setpoints:
        table.add(
            entry.setpoint.degf,
            entry.soak_time.format(),
            entry.worst_high.degf,
            entry.worst_low.degf,
            entry.widest_spread.degf,
            entry.band.plus.degf,
            entry.verdict.value,
            ", ".join(r.value for r in entry.reasons),
        )
    return table


def excursion_table(result: SurveyResult) -> Table:
    """Every reading that left the band, across every set point."""
    table = Table(
        columns=[
            Column("setpoint", align=Align.RIGHT, places=0),
            Column("elapsed"),
            Column("sensor"),
            Column("reading", align=Align.RIGHT, places=1),
            Column("deviation", align=Align.RIGHT, places=1),
        ],
        title=f"out of band readings in {result.survey.number}",
    )
    for entry in result.setpoints:
        for excursion in entry.excursions:
            table.add(
                entry.setpoint.degf,
                excursion.elapsed.format(),
                excursion.sensor,
                excursion.reading.degf,
                excursion.deviation.degf,
            )
    return table


def survey_header(result: SurveyResult) -> str:
    survey = result.survey
    return render_kv(
        [
            ("survey", survey.number),
            ("furnace", str(survey.furnace)),
            ("zone", survey.zone),
            ("performed", survey.performed.isoformat()),
            ("sensors", survey.sensor_count),
            ("corners", survey.corner_count),
            ("centre point", "yes" if survey.has_centre else "no"),
            ("set points", len(result.setpoints)),
            ("verdict", result.verdict.value),
        ],
        title="uniformity survey",
    )


def dropout_note(report: DropoutReport) -> str:
    if report.survey_stands and not report.dropouts and not report.never_read:
        return "no sensors lost"
    return render_kv(
        [
            ("lost", report.lost),
            ("allowed", report.allowed),
            ("never read", len(report.never_read)),
            ("verdict", report.verdict.value),
            ("survey stands", "yes" if report.survey_stands else "no"),
        ],
        title="survey sensor losses",
    )


def due_board(histories: list[SurveyHistory], on: date, *, grace: int = 0) -> Table:
    """The shop wide survey board, most overdue first."""
    table = Table(
        columns=[
            Column("furnace"),
            Column("zone"),
            Column("interval"),
            Column("last pass"),
            Column("due"),
            Column("days", align=Align.RIGHT),
            Column("qualified"),
            Column("state"),
        ],
        title=f"uniformity surveys due as of {on.isoformat()}",
    )
    entries = [(h, h.due(on, grace=grace)) for h in histories]
    entries.sort(
        key=lambda pair: (
            pair[1].days_left is not None,
            pair[1].days_left or 0,
            str(pair[1].furnace),
        )
    )
    for history, entry in entries:
        qualified = history.qualified()
        table.add(
            str(entry.furnace),
            entry.zone,
            str(entry.interval),
            entry.last_passed.isoformat() if entry.last_passed else None,
            entry.due.isoformat() if entry.due else None,
            entry.days_left,
            str(qualified) if qualified is not None else None,
            "never surveyed"
            if entry.never_surveyed
            else ("overdue" if entry.overdue else "in date"),
        )
    return table
