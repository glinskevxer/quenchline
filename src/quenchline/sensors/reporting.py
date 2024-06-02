"""Printed views of the sensor register."""

from __future__ import annotations

from datetime import date

from ..report.table import Align, Column, Table, render_kv
from ..temperature import Temperature
from .record import SensorRole
from .register import SensorRegister, calibration_interval
from .usage import assess


def register_table(register: SensorRegister, on: date) -> Table:
    """One row per couple, with the number that decides whether it stays."""
    table = Table(
        columns=[
            Column("tag"),
            Column("type", align=Align.CENTRE),
            Column("build"),
            Column("role"),
            Column("status"),
            Column("uses", align=Align.RIGHT),
            Column("left"),
            Column("cal due"),
            Column("overdue", align=Align.CENTRE),
        ],
        title="thermocouple register",
    )
    for couple in register.all():
        ledger = register.ledger(couple.tag)
        life = assess(couple.kind, couple.construction, couple.role, ledger)
        certificate = couple.certificate
        due_on = (
            certificate.expires(calibration_interval(couple))
            if certificate is not None
            else None
        )
        due = None if due_on is None else due_on.isoformat()
        overdue = "-" if due_on is None else ("yes" if due_on < on else "no")
        table.add(
            str(couple.tag),
            couple.kind.value,
            couple.construction.value,
            couple.role.value,
            couple.status.value,
            life.uses,
            "spent" if life.is_spent else life.reason,
            due,
            overdue,
        )
    return table


def eligibility_table(
    register: SensorRegister,
    role: SensorRole,
    at: Temperature,
    on: date,
) -> Table:
    """Who can take one job, and why the rest cannot."""
    table = Table(
        columns=[Column("tag"), Column("verdict"), Column("reason")],
        title=f"{role.value} sensors at {at.format()}",
    )
    for couple in register.all():
        result = register.check(couple.tag, role, at, on)
        table.add(
            str(couple.tag),
            "eligible" if result.is_eligible else "refused",
            "; ".join(result.detail) if result.detail else "",
        )
    return table


def register_summary(register: SensorRegister, on: date) -> str:
    """The header block that goes above either table."""
    spent = register.spent()
    uncalibrated = [c for c in register.all() if not c.is_calibrated]
    return render_kv(
        [
            ("as of", on.isoformat()),
            ("thermocouples", len(register)),
            ("in service", len(register.in_service())),
            ("life spent", len(spent)),
            ("no certificate", len(uncalibrated)),
        ],
        title="sensor register summary",
    )
