from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from quenchline.errors import NotFoundError, ValidationError
from quenchline.ingest.mapping import ColumnMap, MappingProfile, TimeUnit
from quenchline.ingest.pipeline import (
    Outcome,
    RunResult,
    import_folder,
    import_text,
)
from quenchline.ingest.profiles import ProfileLibrary
from quenchline.ingest.quarantine import ImportLog
from quenchline.loads.trace import ChannelRole
from quenchline.temperature import Scale

STARTED = datetime(2025, 2, 5, 6, 30)

PROFILE = MappingProfile(
    name="test rig",
    time_heading="Elapsed (min)",
    time_unit=TimeUnit.MINUTES,
    scale=Scale.FAHRENHEIT,
    columns=(ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),),
)

GOOD = "Elapsed (min),Channel 1\n0,100\n30,1545\n60,1552\n"
DIRTY = "Elapsed (min),Channel 1\n0,100\nsoon,1545\nlater,1550\n"
JUNK = "Channel 1\n100\n"


def library() -> ProfileLibrary:
    lib = ProfileLibrary()
    lib.add(PROFILE)
    return lib


def test_a_clean_file_is_imported() -> None:
    result = import_text("run.csv", GOOD, "test rig", STARTED, library(), ImportLog())
    assert result.imported
    assert result.outcome is Outcome.IMPORTED
    assert result.trace is not None
    assert str(result) == "run.csv: imported"


def test_importing_records_the_file_in_the_log() -> None:
    log = ImportLog()
    import_text("run.csv", GOOD, "test rig", STARTED, library(), log)
    assert len(log) == 1


def test_the_same_content_twice_is_a_duplicate() -> None:
    log = ImportLog()
    lib = library()
    import_text("run.csv", GOOD, "test rig", STARTED, lib, log)
    again = import_text("copy.csv", GOOD, "test rig", STARTED, lib, log)
    assert again.outcome is Outcome.DUPLICATE
    assert "run.csv" in again.detail
    assert again.trace is None


def test_an_unknown_profile_is_an_error() -> None:
    with pytest.raises(NotFoundError):
        import_text("run.csv", GOOD, "nothing", STARTED, library(), ImportLog())


def test_a_file_the_profile_cannot_read_is_unreadable() -> None:
    result = import_text("junk.csv", JUNK, "test rig", STARTED, library(), ImportLog())
    assert result.outcome is Outcome.UNREADABLE
    assert result.detail
    assert not result.imported


def test_too_many_bad_rows_rejects_the_whole_file() -> None:
    result = import_text("dirty.csv", DIRTY, "test rig", STARTED, library(), ImportLog())
    assert result.outcome is Outcome.TOO_MANY_BAD_ROWS
    assert "2 of 3 rows rejected" in result.detail


def test_a_generous_tolerance_lets_the_same_file_through() -> None:
    result = import_text(
        "dirty.csv", DIRTY, "test rig", STARTED, library(), ImportLog(), tolerance=0.9
    )
    assert result.imported
    assert result.quarantine.rejected == 2


def test_a_rejected_file_is_not_recorded_in_the_log() -> None:
    log = ImportLog()
    import_text("dirty.csv", DIRTY, "test rig", STARTED, library(), log)
    assert len(log) == 0


def test_a_file_with_no_usable_rows_at_all() -> None:
    text = "Elapsed (min),Channel 1\nsoon,1545\n"
    result = import_text(
        "empty.csv", text, "test rig", STARTED, library(), ImportLog(), tolerance=1.0
    )
    assert result.outcome is Outcome.NO_ROWS


def test_a_run_gathers_every_file(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text(GOOD)
    (tmp_path / "b.csv").write_text(GOOD.replace("1552", "1553"))
    (tmp_path / "c.txt").write_text(GOOD)
    run = import_folder(tmp_path, "test rig", STARTED, library(), ImportLog())
    assert len(run) == 2
    assert [f.name for f in run.files] == ["a.csv", "b.csv"]
    assert len(run.traces()) == 2


def test_a_run_separates_the_rejects(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text(GOOD)
    (tmp_path / "b.csv").write_text(DIRTY)
    run = import_folder(tmp_path, "test rig", STARTED, library(), ImportLog())
    assert [f.name for f in run.imported] == ["a.csv"]
    assert [f.name for f in run.rejected] == ["b.csv"]


def test_a_run_counts_outcomes(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text(GOOD)
    (tmp_path / "b.csv").write_text(GOOD)
    run = import_folder(tmp_path, "test rig", STARTED, library(), ImportLog())
    counts = run.by_outcome()
    assert counts[Outcome.IMPORTED] == 1
    assert counts[Outcome.DUPLICATE] == 1


def test_a_pattern_can_be_given(tmp_path: Path) -> None:
    (tmp_path / "a.dat").write_text(GOOD)
    run = import_folder(tmp_path, "test rig", STARTED, library(), ImportLog(), pattern="*.dat")
    assert len(run) == 1


def test_a_missing_folder_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        import_folder(tmp_path / "nope", "test rig", STARTED, library(), ImportLog())


def test_an_empty_run_reports_nothing() -> None:
    run = RunResult()
    assert len(run) == 0
    assert run.traces() == []
    assert set(run.by_outcome().values()) == {0}
