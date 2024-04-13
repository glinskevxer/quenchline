"""Plain text tables.

Every report this package produces ends up either taped to a job traveller or
pasted into an email, so the output is fixed width text and nothing else. No
colour, no box drawing characters, nothing that a 1990s label printer will turn
into mojibake.

The rules are boring on purpose. Numbers right align, text left aligns, a column
is as wide as its widest cell or its header, and a cell longer than an explicit
width is truncated with a trailing ``~`` so a reader can see it was cut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..errors import ValidationError


class Align(Enum):
    LEFT = "left"
    RIGHT = "right"
    CENTRE = "centre"


@dataclass(frozen=True)
class Column:
    """One column of a table."""

    header: str
    align: Align = Align.LEFT
    width: int | None = None
    places: int | None = None

    def __post_init__(self) -> None:
        if self.width is not None and self.width < 1:
            raise ValidationError("column width must be at least one", field="width")
        if self.places is not None and self.places < 0:
            raise ValidationError("decimal places cannot be negative", field="places")

    def format_cell(self, value: object) -> str:
        if value is None:
            return "-"
        if self.places is not None and isinstance(value, int | float):
            return f"{float(value):.{self.places}f}"
        return str(value)


def _pad(text: str, width: int, align: Align) -> str:
    if len(text) > width:
        return text[: width - 1] + "~" if width > 1 else text[:width]
    if align is Align.RIGHT:
        return text.rjust(width)
    if align is Align.CENTRE:
        return text.center(width)
    return text.ljust(width)


@dataclass
class Table:
    """A table of rows, rendered to fixed width text."""

    columns: list[Column]
    rows: list[list[object]] = field(default_factory=list)
    title: str | None = None
    gap: str = "  "

    def add(self, *values: object) -> None:
        if len(values) != len(self.columns):
            raise ValidationError(
                f"row has {len(values)} cells, table has {len(self.columns)} columns",
                field="row",
            )
        self.rows.append(list(values))

    def extend(self, rows: list[list[object]]) -> None:
        for row in rows:
            self.add(*row)

    @property
    def is_empty(self) -> bool:
        return not self.rows

    def widths(self) -> list[int]:
        widths: list[int] = []
        for index, column in enumerate(self.columns):
            if column.width is not None:
                widths.append(column.width)
                continue
            longest = len(column.header)
            for row in self.rows:
                longest = max(longest, len(column.format_cell(row[index])))
            widths.append(longest)
        return widths

    def render(self) -> str:
        widths = self.widths()
        lines: list[str] = []
        if self.title:
            lines.append(self.title)
            lines.append("=" * len(self.title))
        header = self.gap.join(
            _pad(column.header, width, column.align)
            for column, width in zip(self.columns, widths, strict=True)
        )
        lines.append(header.rstrip())
        lines.append(self.gap.join("-" * width for width in widths))
        if self.is_empty:
            lines.append("(no rows)")
        for row in self.rows:
            cells = [
                _pad(column.format_cell(value), width, column.align)
                for column, value, width in zip(self.columns, row, widths, strict=True)
            ]
            lines.append(self.gap.join(cells).rstrip())
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.render()


def render_kv(pairs: list[tuple[str, object]], *, title: str | None = None) -> str:
    """A two column key/value block, used for report headers."""
    if not pairs:
        return title or ""
    label_width = max(len(key) for key, _ in pairs)
    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append("=" * len(title))
    for key, value in pairs:
        rendered = "-" if value is None else str(value)
        lines.append(f"{key.ljust(label_width)}  {rendered}")
    return "\n".join(lines)
