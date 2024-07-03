"""Printed views of the furnace register."""

from __future__ import annotations

from ..report.table import Align, Column, Table, render_kv
from ..temperature import Temperature
from .register import FurnaceRegister


def furnace_table(register: FurnaceRegister) -> Table:
    table = Table(
        columns=[
            Column("furnace"),
            Column("class", align=Align.RIGHT),
            Column("inst", align=Align.CENTRE),
            Column("band", align=Align.RIGHT, places=0),
            Column("zones", align=Align.RIGHT),
            Column("qualified"),
            Column("status"),
        ],
        title="furnace register",
    )
    for furnace in register.all():
        table.add(
            str(furnace.tag),
            furnace.furnace_class.value,
            furnace.instrumentation.value,
            furnace.tolerance.degf,
            len(furnace.zones),
            str(furnace.qualified) if furnace.qualified is not None else None,
            furnace.status.value,
        )
    return table


def deficiency_table(register: FurnaceRegister) -> Table:
    table = Table(
        columns=[Column("furnace"), Column("claims"), Column("shortfall")],
        title="instrumentation shortfalls",
    )
    for furnace, found in register.deficient():
        table.add(
            str(furnace.tag),
            f"type {furnace.instrumentation.value}",
            ", ".join(d.value for d in found),
        )
    return table


def capability_summary(register: FurnaceRegister, at: Temperature) -> str:
    able = register.able_to_run(at)
    tightest = register.tightest_tolerance()
    return render_kv(
        [
            ("temperature", at.format()),
            ("furnaces", len(register)),
            ("in service", len(register.in_service())),
            ("able to run", len(able)),
            ("tightest band", str(tightest.tolerance) if tightest else None),
        ],
        title="furnace capability",
    )
