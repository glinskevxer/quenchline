"""The mapping profiles the shop actually has, and how to load more.

Three loggers are wired up here because three loggers are what the shop owns.
Anything else arrives as a TOML file rather than as a code change, because a new
logger turning up on a Tuesday should not need a release.

The TOML shape is deliberately flat and boring:

    [[profile]]
    name = "honeywell dr4500"
    time_heading = "Time"
    time_unit = "clock"
    scale = "F"
    delimiter = ","

      [[profile.column]]
      heading = "Pen 1"
      key = "C1"
      role = "control"
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ConflictError, NotFoundError, ValidationError
from ..loads.trace import ChannelRole
from ..temperature import Scale
from .mapping import ColumnMap, MappingProfile, TimeUnit

EUROTHERM_6100 = MappingProfile(
    name="eurotherm 6100",
    time_heading="Elapsed (min)",
    time_unit=TimeUnit.MINUTES,
    scale=Scale.FAHRENHEIT,
    columns=(
        ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),
        ColumnMap("Channel 2", "R1", ChannelRole.RECORD),
        ColumnMap("Channel 3", "L1", ChannelRole.LOAD),
        ColumnMap("Channel 4", "L2", ChannelRole.LOAD),
    ),
)

HONEYWELL_DR4500 = MappingProfile(
    name="honeywell dr4500",
    time_heading="Time",
    time_unit=TimeUnit.CLOCK,
    scale=Scale.FAHRENHEIT,
    columns=(
        ColumnMap("Pen 1", "C1", ChannelRole.CONTROL),
        ColumnMap("Pen 2", "O1", ChannelRole.OVER_TEMPERATURE),
    ),
    dropout_markers=("", "---", "OPEN", "####"),
)

DATAPAQ_TP3 = MappingProfile(
    name="datapaq tp3",
    time_heading="Seconds",
    time_unit=TimeUnit.SECONDS,
    scale=Scale.CELSIUS,
    columns=(
        ColumnMap("Probe 1", "L1", ChannelRole.LOAD),
        ColumnMap("Probe 2", "L2", ChannelRole.LOAD),
        ColumnMap("Probe 3", "L3", ChannelRole.LOAD),
        ColumnMap("Ambient", "A1", ChannelRole.AMBIENT),
    ),
    delimiter=";",
)

BUILT_IN = (EUROTHERM_6100, HONEYWELL_DR4500, DATAPAQ_TP3)


@dataclass
class ProfileLibrary:
    """Every mapping profile the shop can read a file with."""

    profiles: dict[str, MappingProfile] = field(default_factory=dict)

    @classmethod
    def with_built_ins(cls) -> ProfileLibrary:
        library = cls()
        for profile in BUILT_IN:
            library.add(profile)
        return library

    def add(self, profile: MappingProfile) -> None:
        key = profile.name.strip().lower()
        if key in self.profiles:
            raise ConflictError("mapping profile", profile.name)
        self.profiles[key] = profile

    def get(self, name: str) -> MappingProfile:
        key = name.strip().lower()
        if key not in self.profiles:
            raise NotFoundError("mapping profile", name)
        return self.profiles[key]

    def names(self) -> list[str]:
        return sorted(self.profiles)

    def __len__(self) -> int:
        return len(self.profiles)

    def __contains__(self, name: object) -> bool:
        return str(name).strip().lower() in self.profiles

    def load_file(self, path: Path) -> list[MappingProfile]:
        if not path.exists():
            raise ValidationError(f"no profile file at {path}", field="path")
        with path.open("rb") as handle:
            document = tomllib.load(handle)
        return self.load_mapping(document)

    def load_mapping(self, document: dict[str, Any]) -> list[MappingProfile]:
        entries = document.get("profile")
        if not isinstance(entries, list) or not entries:
            raise ValidationError("the file has no profile entries", field="profile")
        added: list[MappingProfile] = []
        for entry in entries:
            profile = build_profile(entry)
            self.add(profile)
            added.append(profile)
        return added


def build_profile(entry: dict[str, Any]) -> MappingProfile:
    """Build one profile from a parsed TOML table."""
    for required in ("name", "time_heading", "time_unit", "scale"):
        if required not in entry:
            raise ValidationError(f"a profile needs {required}", field=required)
    columns_raw = entry.get("column")
    if not isinstance(columns_raw, list) or not columns_raw:
        raise ValidationError("a profile needs columns", field="column")

    columns: list[ColumnMap] = []
    for column in columns_raw:
        for required in ("heading", "key", "role"):
            if required not in column:
                raise ValidationError(f"a column needs {required}", field=required)
        columns.append(
            ColumnMap(str(column["heading"]), str(column["key"]), _role(str(column["role"])))
        )

    markers = entry.get("dropout_markers")
    kwargs: dict[str, Any] = {}
    if markers is not None:
        kwargs["dropout_markers"] = tuple(str(m) for m in markers)
    if "delimiter" in entry:
        kwargs["delimiter"] = str(entry["delimiter"])

    return MappingProfile(
        name=str(entry["name"]),
        time_heading=str(entry["time_heading"]),
        time_unit=_time_unit(str(entry["time_unit"])),
        scale=Scale.parse(str(entry["scale"])),
        columns=tuple(columns),
        **kwargs,
    )


def _role(text: str) -> ChannelRole:
    cleaned = text.strip().lower()
    for role in ChannelRole:
        if role.value == cleaned:
            return role
    raise ValidationError(f"unknown channel role {text!r}", field="role")


def _time_unit(text: str) -> TimeUnit:
    cleaned = text.strip().lower()
    for unit in TimeUnit:
        if unit.value == cleaned:
            return unit
    raise ValidationError(f"unknown time unit {text!r}", field="time_unit")
