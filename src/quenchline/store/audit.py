"""The audit trail.

Not a change log. A change log answers "what does this row look like now", which
the row already answers. This answers "who moved this load to certified, and
when", which nothing else in the database can, because the load record only
holds the state it ended up in.

Two decisions worth stating:

**Entries are never updated or deleted.** There is no method here to do either.
An audit trail somebody can edit is not an audit trail, and the absence of the
method is the enforcement.

**The trail records the decision, not the row.** ``certified L25-0917`` is
useful a year later. A dump of eleven columns before and after is not, and it
carries customer names into a table nobody expected to have to redact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..errors import ValidationError
from .database import Database


@dataclass(frozen=True)
class AuditEntry:
    """One thing somebody did."""

    at: datetime
    action: str
    subject: str
    reference: str
    actor: str = ""
    detail: str = ""
    entry_id: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("action", self.action),
            ("subject", self.subject),
            ("reference", self.reference),
        ):
            if not value.strip():
                raise ValidationError(f"an audit entry needs a {name}", field=name)

    def __str__(self) -> str:
        who = self.actor or "someone"
        return f"{self.at.isoformat(timespec='seconds')} {who} {self.action} {self.reference}"


class AuditTrail:
    """Append only, by construction."""

    def __init__(self, database: Database, *, actor: str = "") -> None:
        self.database = database
        self.actor = actor

    def record(
        self,
        action: str,
        subject: str,
        reference: str,
        *,
        detail: str = "",
        at: datetime | None = None,
        actor: str | None = None,
    ) -> AuditEntry:
        """Write one entry. There is deliberately no way to take it back."""
        entry = AuditEntry(
            at=at or datetime.now(UTC),
            action=action,
            subject=subject,
            reference=reference,
            actor=actor if actor is not None else self.actor,
            detail=detail,
        )
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO audit_entry (at, actor, action, subject, reference, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry.at.isoformat(timespec="seconds"),
                    entry.actor,
                    entry.action,
                    entry.subject,
                    entry.reference,
                    entry.detail,
                ),
            )
        return AuditEntry(
            entry.at,
            entry.action,
            entry.subject,
            entry.reference,
            entry.actor,
            entry.detail,
            cursor.lastrowid,
        )

    def all(self, limit: int = 100) -> list[AuditEntry]:
        if limit < 1:
            raise ValidationError("ask for at least one entry", field="limit")
        rows = self.database.query(
            "SELECT * FROM audit_entry ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [_build(row) for row in rows]

    def against(self, subject: str, reference: str) -> list[AuditEntry]:
        """Everything that happened to one thing, oldest first."""
        rows = self.database.query(
            "SELECT * FROM audit_entry WHERE subject = ? AND reference = ? ORDER BY id",
            (subject, reference),
        )
        return [_build(row) for row in rows]

    def by_action(self, action: str, limit: int = 100) -> list[AuditEntry]:
        rows = self.database.query(
            "SELECT * FROM audit_entry WHERE action = ? ORDER BY id DESC LIMIT ?",
            (action, limit),
        )
        return [_build(row) for row in rows]

    def between(self, start: datetime, end: datetime) -> list[AuditEntry]:
        rows = self.database.query(
            "SELECT * FROM audit_entry WHERE at >= ? AND at <= ? ORDER BY id",
            (
                start.isoformat(timespec="seconds"),
                end.isoformat(timespec="seconds"),
            ),
        )
        return [_build(row) for row in rows]

    def actors(self) -> list[str]:
        rows = self.database.query(
            "SELECT DISTINCT actor FROM audit_entry WHERE actor != '' ORDER BY actor"
        )
        return [row["actor"] for row in rows]

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM audit_entry")
        return int(row["n"]) if row is not None else 0


def _build(row: object) -> AuditEntry:
    mapping = dict(row)  # type: ignore[call-overload]
    return AuditEntry(
        at=datetime.fromisoformat(mapping["at"]),
        action=mapping["action"],
        subject=mapping["subject"],
        reference=mapping["reference"],
        actor=mapping["actor"],
        detail=mapping["detail"],
        entry_id=mapping["id"],
    )
