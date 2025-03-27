"""What every command needs, resolved once.

Click passes a context object down to every subcommand. Ours holds the settings,
the database handle and today's date, and the last of those is the interesting
one: **the date is an option**, not a call to ``date.today()`` buried in a
scheduling function.

Everything in this package that asks "is this overdue" takes the date as an
argument for that reason. It makes the whole shop reproducible from the command
line, so a report can be regenerated exactly as it looked on the day it was
signed, and it means the tests never have to freeze a clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..errors import ValidationError
from ..settings import Settings
from ..store.shop import Shop


@dataclass
class Context:
    """The state one command run works against."""

    settings: Settings
    today: date
    database_path: Path
    _shop: Shop | None = field(default=None, repr=False)

    @classmethod
    def build(
        cls,
        *,
        settings_path: Path | None = None,
        database: Path | None = None,
        today: date | None = None,
        environ: dict[str, str] | None = None,
    ) -> Context:
        settings = Settings.load(settings_path, environ=environ)
        path = database if database is not None else settings.database
        return cls(settings, today or date.today(), path)

    def shop(self) -> Shop:
        """Open the database, once."""
        if self._shop is None:
            self._shop = Shop.open(self.database_path)
        return self._shop

    def close(self) -> None:
        if self._shop is not None:
            self._shop.close()
            self._shop = None

    @property
    def is_open(self) -> bool:
        return self._shop is not None

    def __enter__(self) -> Context:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def parse_day(text: str | None, fallback: date) -> date:
    """Read a ``YYYY-MM-DD`` option, falling back when it was not given."""
    if text is None:
        return fallback
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        raise ValidationError(f"{text!r} is not a date, use YYYY-MM-DD", field="date") from None
