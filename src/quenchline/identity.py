"""The tags and numbers the shop writes on everything.

Nothing in a heat treat shop is identified by a database row id. A furnace is
``HT-04``, a thermocouple is ``TC-01188``, a load is ``L24-0917``, and those
strings are stamped on tags, written on travellers and typed into three
different systems by four different people. This module is the one place that
decides what a valid tag looks like and how a sloppy one is cleaned up.

Normalising is deliberately narrow. Case and surrounding whitespace are fixed
because ``ht-4`` and ``HT-4`` are the same furnace. A missing leading zero is
**not** fixed, because ``TC-118`` and ``TC-0118`` are two different couples and
guessing which one the operator meant is how the wrong calibration gets applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Final, Self

from .errors import ParseError, ValidationError

_TAG_RE: Final = re.compile(
    r"^(?P<prefix>[A-Z]{1,4})-(?P<serial>[0-9]{1,6})(?P<suffix>[A-Z]?)$"
)
_LOT_RE: Final = re.compile(r"^L(?P<year>\d{2})-(?P<serial>\d{4})$")
_WORK_ORDER_RE: Final = re.compile(r"^W(?P<serial>\d{6})(?:-(?P<split>\d{1,2}))?$")


def normalise_code(text: str) -> str:
    """Upper case, trim, and collapse runs of internal whitespace to nothing."""
    return re.sub(r"\s+", "", text.strip().upper())


@dataclass(frozen=True, order=True)
class AssetTag:
    """An equipment tag such as ``HT-04`` or ``TC-01188``.

    Subclasses pin the prefix so a thermocouple tag cannot be handed to a
    function that wants a furnace.
    """

    prefix: str
    serial: int
    suffix: str = ""

    allowed_prefixes: ClassVar[frozenset[str] | None] = None

    def __post_init__(self) -> None:
        allowed = type(self).allowed_prefixes
        if allowed is not None and self.prefix not in allowed:
            raise ValidationError(
                f"prefix {self.prefix!r} is not one of {sorted(allowed)}", field="prefix"
            )
        if self.serial < 0:
            raise ValidationError("serial cannot be negative", field="serial")

    @classmethod
    def parse(cls, text: str) -> Self:
        cleaned = normalise_code(text)
        match = _TAG_RE.match(cleaned)
        if match is None:
            raise ParseError("not an asset tag", text=text, field="tag")
        return cls(
            prefix=match.group("prefix"),
            serial=int(match.group("serial")),
            suffix=match.group("suffix"),
        )

    @property
    def width(self) -> int:
        """Digits the serial is printed with. Fixed per prefix by shop habit."""
        return 5 if self.prefix == "TC" else 2

    def __str__(self) -> str:
        return f"{self.prefix}-{self.serial:0{self.width}d}{self.suffix}"


class FurnaceTag(AssetTag):
    """A furnace or a piece of thermal processing equipment."""

    allowed_prefixes: ClassVar[frozenset[str] | None] = frozenset({"HT", "TF", "QT", "VF"})


class SensorTag(AssetTag):
    """A thermocouple, a probe or a lead wire assembly."""

    allowed_prefixes: ClassVar[frozenset[str] | None] = frozenset({"TC", "PR", "LW"})


class InstrumentTag(AssetTag):
    """A controller, recorder or field test instrument."""

    allowed_prefixes: ClassVar[frozenset[str] | None] = frozenset({"IC", "IR", "IO", "FT"})


@dataclass(frozen=True, order=True)
class LotNumber:
    """A heat lot, written ``L24-0917``: two digit year, four digit serial."""

    year: int
    serial: int

    def __post_init__(self) -> None:
        if not 0 <= self.year <= 99:
            raise ValidationError("lot year is two digits", field="year")
        if not 0 <= self.serial <= 9999:
            raise ValidationError("lot serial is four digits", field="serial")

    @classmethod
    def parse(cls, text: str) -> LotNumber:
        match = _LOT_RE.match(normalise_code(text))
        if match is None:
            raise ParseError("not a lot number", text=text, field="lot")
        return cls(int(match.group("year")), int(match.group("serial")))

    def next(self) -> LotNumber:
        if self.serial == 9999:
            raise ValidationError("lot serial rolled over", field="serial")
        return LotNumber(self.year, self.serial + 1)

    def __str__(self) -> str:
        return f"L{self.year:02d}-{self.serial:04d}"


@dataclass(frozen=True, order=True)
class WorkOrder:
    """A customer work order, optionally split across several loads."""

    serial: int
    split: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.serial <= 999999:
            raise ValidationError("work order serial is six digits", field="serial")
        if self.split is not None and not 1 <= self.split <= 99:
            raise ValidationError("split runs from 1 to 99", field="split")

    @classmethod
    def parse(cls, text: str) -> WorkOrder:
        match = _WORK_ORDER_RE.match(normalise_code(text))
        if match is None:
            raise ParseError("not a work order", text=text, field="work_order")
        split = match.group("split")
        return cls(int(match.group("serial")), int(split) if split is not None else None)

    @property
    def is_split(self) -> bool:
        return self.split is not None

    def base(self) -> WorkOrder:
        return WorkOrder(self.serial)

    def part(self, split: int) -> WorkOrder:
        return WorkOrder(self.serial, split)

    def __str__(self) -> str:
        if self.split is None:
            return f"W{self.serial:06d}"
        return f"W{self.serial:06d}-{self.split}"


def require_sensor_tag(text: str) -> SensorTag:
    """Parse a sensor tag and refuse the serial the shop keeps for scrap wire."""
    tag = SensorTag.parse(text)
    if tag.serial == 0:
        raise ValidationError("serial zero is reserved for uncontrolled wire", field="tag")
    return tag
