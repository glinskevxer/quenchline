"""Rows that could not be read, and files that have been read before.

Two things happen to a datalogger file that a naive importer gets wrong.

**Some rows are unreadable.** A logger that lost power mid write leaves a
truncated line. A technician who opened the file in a spreadsheet and saved it
leaves a stray blank row. Throwing the whole file away for one bad row is
useless, and silently skipping bad rows is worse, because nobody finds out. So
bad rows go to quarantine with the reason and the line number, and the caller
decides what a tolerable number of them is.

**Files get imported twice.** Somebody re-runs the nightly job, or copies the
same file from two folders. Dedupe is by **content hash**, not by filename,
because the same trace arrives under three different names and two different
names arrive holding different traces.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum

from ..errors import ValidationError


class RejectReason(Enum):
    SHORT_ROW = "short_row"
    BAD_TIME = "bad_time"
    BAD_READING = "bad_reading"
    OUT_OF_ORDER = "out_of_order"
    DUPLICATE_TIME = "duplicate_time"
    EMPTY = "empty"

    @property
    def is_structural(self) -> bool:
        """Whether the row was malformed rather than merely unusable."""
        return self in {RejectReason.SHORT_ROW, RejectReason.EMPTY}


@dataclass(frozen=True)
class QuarantinedRow:
    """One row that could not be used, kept with the reason."""

    line: int
    reason: RejectReason
    detail: str
    raw: str

    def __post_init__(self) -> None:
        if self.line < 1:
            raise ValidationError("line numbers start at one", field="line")

    def __str__(self) -> str:
        return f"line {self.line}: {self.reason.value}, {self.detail}"


@dataclass
class Quarantine:
    """Every row one import could not use."""

    rows: list[QuarantinedRow] = field(default_factory=list)
    accepted: int = 0

    def reject(self, line: int, reason: RejectReason, detail: str, raw: str) -> None:
        self.rows.append(QuarantinedRow(line, reason, detail, raw))

    def accept(self) -> None:
        self.accepted += 1

    @property
    def rejected(self) -> int:
        return len(self.rows)

    @property
    def seen(self) -> int:
        return self.accepted + self.rejected

    @property
    def is_clean(self) -> bool:
        return not self.rows

    @property
    def reject_fraction(self) -> float:
        if self.seen == 0:
            return 0.0
        return self.rejected / self.seen

    def by_reason(self) -> dict[RejectReason, int]:
        counts = dict.fromkeys(RejectReason, 0)
        for row in self.rows:
            counts[row.reason] += 1
        return counts

    def within(self, limit: float) -> bool:
        """Whether the rejection rate is inside a tolerable fraction."""
        if not 0 <= limit <= 1:
            raise ValidationError("the limit is a fraction", field="limit")
        return self.reject_fraction <= limit + 1e-9

    def __len__(self) -> int:
        return len(self.rows)


def content_hash(text: str) -> str:
    """A stable hash of a file's content, used for dedupe."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalised_hash(text: str) -> str:
    """A hash that ignores line endings and trailing whitespace.

    The same trace copied through a Windows share and a Linux one differs only
    in line endings, and treating those as two different files means importing
    the same run twice.
    """
    lines = [
        line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    while lines and not lines[-1]:
        lines.pop()
    return content_hash("\n".join(lines))


@dataclass
class ImportLog:
    """Which files have already been read."""

    hashes: dict[str, str] = field(default_factory=dict)

    def seen(self, digest: str) -> bool:
        return digest in self.hashes

    def record(self, digest: str, name: str) -> None:
        if digest in self.hashes:
            raise ValidationError(
                f"already imported as {self.hashes[digest]!r}", field="digest"
            )
        self.hashes[digest] = name

    def name_for(self, digest: str) -> str | None:
        return self.hashes.get(digest)

    def __len__(self) -> int:
        return len(self.hashes)
