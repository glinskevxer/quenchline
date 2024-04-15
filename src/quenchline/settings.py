"""Shop settings.

Everything that varies between one heat treat shop and the next, and nothing
that varies between one job and the next. A customer specification that says
"survey every three months" belongs on the furnace record, not here. What
belongs here is the shop's own habits: which scale the paperwork is printed on,
how many days of grace the scheduler allows before it shouts, where the database
file lives.

Settings load from a TOML file, and every key has a default, so a shop that has
never written a settings file still gets a working install. An environment
variable of the form ``QUENCHLINE_<KEY>`` beats the file, which is how the test
harness and the nightly job override a single value without editing anything.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from .calendar_rules import DueRule
from .errors import ParseError, ValidationError
from .temperature import Scale

ENV_PREFIX = "QUENCHLINE_"


@dataclass(frozen=True)
class Settings:
    """The shop wide configuration."""

    database: Path = Path("quenchline.sqlite")
    report_scale: Scale = Scale.FAHRENHEIT
    reading_step: float = 1.0
    schedule_grace_days: int = 0
    default_due_rule: DueRule = DueRule.ANNIVERSARY
    quarantine_dir: Path = Path("quarantine")
    shop_name: str = "unnamed shop"
    certificate_prefix: str = "CERT"

    def __post_init__(self) -> None:
        if self.reading_step <= 0:
            raise ValidationError("reading step must be positive", field="reading_step")
        if self.schedule_grace_days < 0:
            raise ValidationError("grace days cannot be negative", field="schedule_grace_days")
        if not self.certificate_prefix.strip():
            raise ValidationError(
                "certificate prefix cannot be blank", field="certificate_prefix"
            )

    @classmethod
    def defaults(cls) -> Settings:
        return cls()

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValidationError(f"unknown settings: {', '.join(unknown)}", field="settings")
        coerced: dict[str, Any] = {}
        for key, raw in values.items():
            coerced[key] = _coerce(key, raw)
        return cls(**coerced)

    @classmethod
    def load(
        cls, path: Path | None = None, *, environ: dict[str, str] | None = None
    ) -> Settings:
        """Read a TOML file, then let the environment override single keys."""
        values: dict[str, Any] = {}
        if path is not None:
            if not path.exists():
                raise ValidationError(f"no settings file at {path}", field="path")
            with path.open("rb") as handle:
                loaded = tomllib.load(handle)
            section = loaded.get("quenchline", loaded)
            if not isinstance(section, dict):
                raise ValidationError("the quenchline table is not a table", field="settings")
            values.update(section)
        env = os.environ if environ is None else environ
        for f in fields(cls):
            key = ENV_PREFIX + f.name.upper()
            if key in env:
                values[f.name] = env[key]
        return cls.from_mapping(values)

    def replace(self, **changes: Any) -> Settings:
        current = {f.name: getattr(self, f.name) for f in fields(self)}
        current.update({key: _coerce(key, value) for key, value in changes.items()})
        return Settings.from_mapping(current)

    def as_mapping(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _coerce(key: str, raw: Any) -> Any:
    if key in {"database", "quarantine_dir"}:
        return Path(raw) if not isinstance(raw, Path) else raw
    if key == "report_scale":
        return raw if isinstance(raw, Scale) else Scale.parse(str(raw))
    if key == "default_due_rule":
        if isinstance(raw, DueRule):
            return raw
        try:
            return DueRule(str(raw).strip().lower())
        except ValueError:
            raise ParseError("not a due rule", text=str(raw), field=key) from None
    if key == "reading_step":
        return float(raw)
    if key == "schedule_grace_days":
        return int(raw)
    return str(raw)
