from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.ingest.quarantine import (
    ImportLog,
    Quarantine,
    QuarantinedRow,
    RejectReason,
    content_hash,
    normalised_hash,
)


def test_reject_reasons_split_structural_from_unusable() -> None:
    assert RejectReason.SHORT_ROW.is_structural
    assert RejectReason.EMPTY.is_structural
    assert not RejectReason.BAD_TIME.is_structural
    assert not RejectReason.OUT_OF_ORDER.is_structural


def test_a_quarantined_row_keeps_its_line_and_reason() -> None:
    row = QuarantinedRow(12, RejectReason.BAD_TIME, "not a number", "soon,1550")
    assert str(row) == "line 12: bad_time, not a number"
    with pytest.raises(ValidationError):
        QuarantinedRow(0, RejectReason.EMPTY, "blank", "")


def test_an_empty_quarantine_is_clean() -> None:
    q = Quarantine()
    assert q.is_clean
    assert q.seen == 0
    assert q.reject_fraction == pytest.approx(0.0)
    assert q.within(0.0)


def test_counts_add_up() -> None:
    q = Quarantine()
    for _ in range(8):
        q.accept()
    q.reject(3, RejectReason.BAD_TIME, "not a number", "soon,1550")
    q.reject(9, RejectReason.SHORT_ROW, "two cells expected", "1550")
    assert q.accepted == 8
    assert q.rejected == 2
    assert q.seen == 10
    assert not q.is_clean
    assert len(q) == 2


def test_reject_fraction_and_tolerance() -> None:
    q = Quarantine()
    for _ in range(9):
        q.accept()
    q.reject(3, RejectReason.BAD_TIME, "not a number", "soon")
    assert q.reject_fraction == pytest.approx(0.1)
    assert q.within(0.1)
    assert not q.within(0.05)


def test_the_tolerance_must_be_a_fraction() -> None:
    with pytest.raises(ValidationError):
        Quarantine().within(2.0)
    with pytest.raises(ValidationError):
        Quarantine().within(-0.1)


def test_by_reason_counts_every_reason() -> None:
    q = Quarantine()
    q.reject(3, RejectReason.BAD_TIME, "x", "y")
    q.reject(4, RejectReason.BAD_TIME, "x", "y")
    q.reject(5, RejectReason.SHORT_ROW, "x", "y")
    counts = q.by_reason()
    assert counts[RejectReason.BAD_TIME] == 2
    assert counts[RejectReason.SHORT_ROW] == 1
    assert counts[RejectReason.EMPTY] == 0


def test_content_hash_is_stable_and_content_sensitive() -> None:
    assert content_hash("a,b\n1,2\n") == content_hash("a,b\n1,2\n")
    assert content_hash("a,b\n1,2\n") != content_hash("a,b\n1,3\n")


def test_normalised_hash_ignores_line_endings() -> None:
    assert normalised_hash("a,b\r\n1,2\r\n") == normalised_hash("a,b\n1,2\n")
    assert normalised_hash("a,b\r1,2\r") == normalised_hash("a,b\n1,2\n")


def test_normalised_hash_ignores_trailing_blank_lines() -> None:
    assert normalised_hash("a,b\n1,2\n\n\n") == normalised_hash("a,b\n1,2")


def test_normalised_hash_ignores_trailing_spaces_on_a_line() -> None:
    assert normalised_hash("a,b   \n1,2\n") == normalised_hash("a,b\n1,2\n")


def test_normalised_hash_still_notices_a_changed_value() -> None:
    assert normalised_hash("a,b\n1,2\n") != normalised_hash("a,b\n1,3\n")


def test_an_import_log_remembers_what_it_has_read() -> None:
    log = ImportLog()
    digest = normalised_hash("a,b\n1,2\n")
    assert not log.seen(digest)
    log.record(digest, "run-2411.csv")
    assert log.seen(digest)
    assert log.name_for(digest) == "run-2411.csv"
    assert len(log) == 1


def test_the_same_content_under_a_different_name_is_refused() -> None:
    log = ImportLog()
    digest = normalised_hash("a,b\n1,2\n")
    log.record(digest, "run-2411.csv")
    with pytest.raises(ValidationError) as caught:
        log.record(digest, "copy of run-2411.csv")
    assert "run-2411.csv" in str(caught.value)


def test_a_different_file_under_the_same_name_is_allowed() -> None:
    log = ImportLog()
    log.record(normalised_hash("a,b\n1,2\n"), "run.csv")
    log.record(normalised_hash("a,b\n1,3\n"), "run.csv")
    assert len(log) == 2


def test_an_unknown_digest_has_no_name() -> None:
    assert ImportLog().name_for("deadbeef") is None
