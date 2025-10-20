"""Database commands."""

from __future__ import annotations

from pathlib import Path

import click

from ..report.table import Align, Column, Table, render_kv
from ..store.maintenance import backup, check, page_stats, restore, row_counts, vacuum
from .context import Context


@click.group("db")
def db_group() -> None:
    """Open, check and look after the shop database."""


@db_group.command("status")
@click.pass_obj
def status(context: Context) -> None:
    """Print the schema version and what is in the file."""
    shop = context.shop()
    applied = shop.database.applied()
    stats = page_stats(shop.database)
    click.echo(
        render_kv(
            [
                ("database", str(context.database_path)),
                ("schema version", shop.database.version),
                ("migrations applied", len(applied)),
                ("last migration", applied[-1].name if applied else None),
                ("pages", stats["page_count"]),
                ("free pages", stats["freelist_count"]),
                ("page size", stats["page_size"]),
            ],
            title="database",
        )
    )


@db_group.command("migrations")
@click.pass_obj
def migrations(context: Context) -> None:
    """List the migrations this file has had applied."""
    table = Table(
        columns=[
            Column("version", align=Align.RIGHT),
            Column("name"),
            Column("checksum"),
            Column("applied"),
        ],
        title="applied migrations",
    )
    for row in context.shop().database.applied():
        table.add(row.version, row.name, row.checksum[:12], row.applied_at)
    click.echo(table.render())


@db_group.command("pending")
@click.pass_obj
def pending(context: Context) -> None:
    """Migrations this file has not had applied yet."""
    database = context.shop().database
    waiting = database.pending()
    if not waiting:
        click.echo(f"schema is current at version {database.version}")
        return
    table = Table(
        columns=[Column("version", align=Align.RIGHT), Column("name")],
        title="pending migrations",
    )
    for migration in waiting:
        table.add(migration.version, migration.name)
    click.echo(table.render())


@db_group.command("counts")
@click.pass_obj
def counts(context: Context) -> None:
    """Row counts per table."""
    table = Table(
        columns=[Column("table"), Column("rows", align=Align.RIGHT)], title="row counts"
    )
    for name, count in sorted(row_counts(context.shop().database).items()):
        table.add(name, count)
    click.echo(table.render())


@db_group.command("check")
@click.pass_obj
def integrity(context: Context) -> None:
    """Run the integrity and foreign key checks."""
    report = check(context.shop().database)
    click.echo(str(report))
    if not report.is_clean:
        raise SystemExit(1)


@db_group.command("vacuum")
@click.pass_obj
def compact(context: Context) -> None:
    """Rewrite the file and reclaim free pages."""
    shop = context.shop()
    before = page_stats(shop.database)
    vacuum(shop.database)
    after = page_stats(shop.database)
    click.echo(
        f"pages {before['page_count']} to {after['page_count']}, "
        f"free {before['freelist_count']} to {after['freelist_count']}"
    )


@db_group.command("backup")
@click.argument("destination", type=click.Path(path_type=Path))
@click.pass_obj
def take_backup(context: Context, destination: Path) -> None:
    """Take a consistent copy of the database."""
    written = backup(context.shop().database, destination)
    click.echo(f"backed up to {written}")


@db_group.command("restore")
@click.argument("source", type=click.Path(path_type=Path))
@click.option("--overwrite", is_flag=True, help="replace the current database")
@click.pass_obj
def put_back(context: Context, source: Path, overwrite: bool) -> None:
    """Put a backup back over the current database."""
    context.close()
    written = restore(source, context.database_path, overwrite=overwrite)
    click.echo(f"restored {written}")
