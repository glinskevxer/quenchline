"""One import run, from a folder of files to a set of traces.

The pipeline is thin on purpose. Everything hard is already done by the reader,
the profile and the quarantine; this walks the files, keeps the import log
honest, and decides whether the run as a whole is acceptable.

The one judgement it does make is the **tolerance**. A file with two bad rows in
four thousand is fine. A file with four hundred bad rows in four thousand means
the profile is wrong, or the file is not what it claims to be, and importing it
is worse than not importing it. So a file over the tolerance is rejected whole
even though it produced a usable trace, and the reason is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..errors import ValidationError
from ..loads.trace import Trace
from .profiles import ProfileLibrary
from .quarantine import ImportLog, Quarantine
from .reader import read_text

DEFAULT_TOLERANCE = 0.02


class Outcome(Enum):
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    TOO_MANY_BAD_ROWS = "too_many_bad_rows"
    UNREADABLE = "unreadable"
    NO_ROWS = "no_rows"

    @property
    def is_success(self) -> bool:
        return self is Outcome.IMPORTED


@dataclass(frozen=True)
class FileResult:
    """What happened to one file."""

    name: str
    outcome: Outcome
    trace: Trace | None
    quarantine: Quarantine
    digest: str
    detail: str = ""

    @property
    def imported(self) -> bool:
        return self.outcome.is_success

    def __str__(self) -> str:
        return f"{self.name}: {self.outcome.value}" + (
            f" ({self.detail})" if self.detail else ""
        )


@dataclass
class RunResult:
    """What happened to a whole import run."""

    files: list[FileResult] = field(default_factory=list)

    @property
    def imported(self) -> list[FileResult]:
        return [f for f in self.files if f.imported]

    @property
    def rejected(self) -> list[FileResult]:
        return [f for f in self.files if not f.imported]

    def traces(self) -> list[Trace]:
        return [f.trace for f in self.imported if f.trace is not None]

    def by_outcome(self) -> dict[Outcome, int]:
        counts = dict.fromkeys(Outcome, 0)
        for result in self.files:
            counts[result.outcome] += 1
        return counts

    def __len__(self) -> int:
        return len(self.files)


def import_text(
    name: str,
    text: str,
    profile_name: str,
    started: datetime,
    library: ProfileLibrary,
    log: ImportLog,
    *,
    tolerance: float = DEFAULT_TOLERANCE,
) -> FileResult:
    """Import one file's text, honouring the import log and the tolerance."""
    profile = library.get(profile_name)
    try:
        result = read_text(text, profile, started, source=name)
    except ValidationError as error:
        return FileResult(name, Outcome.UNREADABLE, None, Quarantine(), "", str(error))

    if log.seen(result.digest):
        return FileResult(
            name,
            Outcome.DUPLICATE,
            None,
            result.quarantine,
            result.digest,
            f"already imported as {log.name_for(result.digest)!r}",
        )

    if not result.quarantine.within(tolerance):
        return FileResult(
            name,
            Outcome.TOO_MANY_BAD_ROWS,
            None,
            result.quarantine,
            result.digest,
            f"{result.quarantine.rejected} of {result.quarantine.seen} rows rejected",
        )

    if result.trace is None:
        return FileResult(
            name,
            Outcome.NO_ROWS,
            None,
            result.quarantine,
            result.digest,
            "no usable rows",
        )

    log.record(result.digest, name)
    return FileResult(name, Outcome.IMPORTED, result.trace, result.quarantine, result.digest)


def import_folder(
    folder: Path,
    profile_name: str,
    started: datetime,
    library: ProfileLibrary,
    log: ImportLog,
    *,
    pattern: str = "*.csv",
    tolerance: float = DEFAULT_TOLERANCE,
) -> RunResult:
    """Import every matching file in a folder, oldest name first."""
    if not folder.is_dir():
        raise ValidationError(f"{folder} is not a folder", field="folder")
    run = RunResult()
    for path in sorted(folder.glob(pattern)):
        run.files.append(
            import_text(
                path.name,
                path.read_text(),
                profile_name,
                started,
                library,
                log,
                tolerance=tolerance,
            )
        )
    return run
