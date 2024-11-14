"""Printed views of a load and its run."""

from __future__ import annotations

from ..report.table import Align, Column, Table, render_kv
from .deviation import Deviation, worst
from .disposition import Decision, summarise
from .record import Load
from .segment import Segment
from .trace import Trace


def load_header(load: Load) -> str:
    return render_kv(
        [
            ("lot", str(load.lot)),
            ("work order", str(load.work_order)),
            ("furnace", str(load.furnace)),
            ("recipe", load.recipe),
            ("pieces", load.piece_count),
            ("weight", str(load.weight) if load.weight is not None else None),
            ("load sensors", len(load.load_sensors)),
            ("state", load.state.value),
            ("charged", load.charged_at.isoformat(sep=" ") if load.charged_at else None),
            ("finished", load.finished_at.isoformat(sep=" ") if load.finished_at else None),
        ],
        title="load record",
    )


def parts_table(load: Load) -> Table:
    table = Table(
        columns=[
            Column("part number"),
            Column("quantity", align=Align.RIGHT),
            Column("material"),
            Column("description"),
        ],
        title=f"parts on {load.lot}",
    )
    for line in load.parts:
        table.add(
            line.part_number, line.quantity, line.material or None, line.description or None
        )
    return table


def segment_table(segments: tuple[Segment, ...]) -> Table:
    table = Table(
        columns=[
            Column("step"),
            Column("kind"),
            Column("start"),
            Column("end"),
            Column("held"),
            Column("required"),
            Column("channel"),
        ],
        title="cycle steps located on the trace",
    )
    for entry in segments:
        window = entry.window
        required = entry.step.minimum_time
        table.add(
            entry.step.name,
            entry.step.kind.value,
            window.start.format() if window else None,
            window.end.format() if window else None,
            window.length.format() if window else None,
            required.format() if required else None,
            entry.governing_key,
        )
    return table


def deviation_table(findings: tuple[Deviation, ...]) -> Table:
    table = Table(
        columns=[
            Column("severity"),
            Column("kind"),
            Column("step"),
            Column("detail"),
        ],
        title="deviations",
    )
    for finding in findings:
        table.add(finding.severity.value, finding.kind.value, finding.step, finding.detail)
    return table


def channel_table(trace: Trace) -> Table:
    table = Table(
        columns=[
            Column("channel"),
            Column("role"),
            Column("samples", align=Align.RIGHT),
            Column("readings", align=Align.RIGHT),
            Column("peak", align=Align.RIGHT, places=0),
            Column("gaps", align=Align.RIGHT),
            Column("lost", align=Align.RIGHT),
        ],
        title="trace channels",
    )
    for channel in trace.channels:
        peak = channel.peak()
        table.add(
            channel.key,
            channel.role.value,
            len(channel.samples),
            len(channel.readings),
            peak.degf if peak is not None else None,
            len(channel.gaps()),
            len(channel.unbridgeable()),
        )
    return table


def run_summary(load: Load, findings: tuple[Deviation, ...], decision: Decision) -> str:
    counts = summarise(findings)
    highest = worst(findings)
    return render_kv(
        [
            ("lot", str(load.lot)),
            ("recipe", load.recipe),
            ("deviations", len(findings)),
            ("minor", counts["minor"]),
            ("major", counts["major"]),
            ("critical", counts["critical"]),
            ("worst", highest.value if highest is not None else None),
            ("disposition", decision.disposition.value),
            ("ships", "yes" if decision.ships else "no"),
            ("reason", decision.reason),
        ],
        title="run summary",
    )
