"""Audit trail commands."""

from __future__ import annotations

import click

from ..report.table import Column, Table
from ..store.audit import AuditEntry
from .context import Context


@click.group("audit")
def audit_group() -> None:
    """Read the audit trail. Nothing here writes to it."""


@audit_group.command("recent")
@click.option("--limit", type=int, default=20, help="how many entries to show")
@click.pass_obj
def recent(context: Context, limit: int) -> None:
    """The most recent entries, newest first."""
    entries = context.shop().audit.all(limit)
    if not entries:
        click.echo("nothing has been recorded yet")
        return
    click.echo(_table(entries, "recent activity").render())


@audit_group.command("against")
@click.argument("subject")
@click.argument("reference")
@click.pass_obj
def against(context: Context, subject: str, reference: str) -> None:
    """Everything that happened to one thing, oldest first."""
    entries = context.shop().audit.against(subject, reference)
    if not entries:
        click.echo(f"nothing recorded against {subject} {reference}")
        return
    click.echo(_table(entries, f"{subject} {reference}").render())


@audit_group.command("action")
@click.argument("action")
@click.option("--limit", type=int, default=20)
@click.pass_obj
def by_action(context: Context, action: str, limit: int) -> None:
    """Every time one thing was done."""
    entries = context.shop().audit.by_action(action, limit)
    if not entries:
        click.echo(f"nobody has {action} anything")
        return
    click.echo(_table(entries, action).render())


def _table(entries: list[AuditEntry], title: str) -> Table:
    table = Table(
        columns=[
            Column("when"),
            Column("who"),
            Column("action"),
            Column("subject"),
            Column("reference"),
            Column("detail"),
        ],
        title=title,
    )
    for entry in entries:
        table.add(
            entry.at.isoformat(sep=" ", timespec="seconds"),
            entry.actor or None,
            entry.action,
            entry.subject,
            entry.reference,
            entry.detail or None,
        )
    return table
