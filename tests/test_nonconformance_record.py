from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import StateError, ValidationError
from quenchline.loads.disposition import Disposition
from quenchline.nonconformance.record import NcrStage, NcrSubject, Nonconformance

RAISED = date(2025, 1, 8)


def ncr(**changes: object) -> Nonconformance:
    base: dict[str, object] = {
        "number": "NCR-25-014",
        "subject": NcrSubject.LOAD,
        "reference": "L24-0917",
        "raised_on": RAISED,
        "summary": "soak short by twelve minutes",
    }
    base.update(changes)
    return Nonconformance(**base)  # type: ignore[arg-type]


def test_subject_groups() -> None:
    assert not NcrSubject.LOAD.is_equipment
    assert NcrSubject.FURNACE.is_equipment
    assert NcrSubject.INSTRUMENT.can_hold_work_back
    assert NcrSubject.SENSOR.can_hold_work_back
    assert not NcrSubject.LOAD.can_hold_work_back
    assert not NcrSubject.BATH.can_hold_work_back


def test_stage_groups() -> None:
    assert NcrStage.RAISED.is_open
    assert NcrStage.ACTIONED.is_open
    assert not NcrStage.CLOSED.is_open
    assert NcrStage.CLOSED.is_final
    assert NcrStage.VOIDED.is_final


def test_validation() -> None:
    with pytest.raises(ValidationError):
        ncr(number="  ")
    with pytest.raises(ValidationError):
        ncr(reference="")
    with pytest.raises(ValidationError):
        ncr(summary=" ")


def test_a_suspect_window_needs_both_ends() -> None:
    with pytest.raises(ValidationError):
        ncr(suspect_from=RAISED)
    with pytest.raises(ValidationError):
        ncr(suspect_to=RAISED)
    with pytest.raises(ValidationError):
        ncr(suspect_from=date(2025, 2, 1), suspect_to=date(2025, 1, 1))


def test_a_new_report_is_open() -> None:
    report = ncr()
    assert report.stage is NcrStage.RAISED
    assert report.is_open
    assert not report.has_suspect_window
    assert str(report) == "NCR-25-014 load L24-0917 (raised)"


def test_the_full_path_to_closure() -> None:
    report = ncr()
    report = report.disposition_as(Disposition.REWORK, date(2025, 1, 9))
    assert report.stage is NcrStage.DISPOSITIONED
    assert report.disposition is Disposition.REWORK
    report = report.action(date(2025, 1, 10), "cycle rerun as lot L25-0004")
    assert report.stage is NcrStage.ACTIONED
    report = report.close(date(2025, 1, 11))
    assert report.stage is NcrStage.CLOSED
    assert not report.is_open


def test_stages_cannot_be_skipped() -> None:
    report = ncr()
    with pytest.raises(StateError):
        report.action(date(2025, 1, 10), "done")
    with pytest.raises(StateError):
        report.close(date(2025, 1, 10))


def test_a_disposition_can_only_be_given_once() -> None:
    report = ncr().disposition_as(Disposition.REWORK, date(2025, 1, 9))
    with pytest.raises(StateError):
        report.disposition_as(Disposition.SCRAP, date(2025, 1, 10))


def test_dates_must_run_forward() -> None:
    report = ncr()
    with pytest.raises(ValidationError):
        report.disposition_as(Disposition.REWORK, date(2025, 1, 1))
    dispositioned = report.disposition_as(Disposition.REWORK, date(2025, 1, 9))
    with pytest.raises(ValidationError):
        dispositioned.action(date(2025, 1, 8), "done")
    actioned = dispositioned.action(date(2025, 1, 10), "done")
    with pytest.raises(ValidationError):
        actioned.close(date(2025, 1, 9))


def test_an_action_needs_a_note() -> None:
    report = ncr().disposition_as(Disposition.REWORK, date(2025, 1, 9))
    with pytest.raises(ValidationError):
        report.action(date(2025, 1, 10), "   ")


def test_an_equipment_report_cannot_close_without_a_suspect_window() -> None:
    report = (
        ncr(subject=NcrSubject.INSTRUMENT, reference="IC-04")
        .disposition_as(Disposition.REVIEW, date(2025, 1, 9))
        .action(date(2025, 1, 10), "instrument recalibrated")
    )
    with pytest.raises(StateError):
        report.close(date(2025, 1, 11))


def test_the_same_report_closes_once_the_window_is_named() -> None:
    report = (
        ncr(subject=NcrSubject.INSTRUMENT, reference="IC-04")
        .with_suspect_window(date(2024, 10, 1), date(2025, 1, 8))
        .disposition_as(Disposition.REVIEW, date(2025, 1, 9))
        .action(date(2025, 1, 10), "instrument recalibrated")
    )
    closed = report.close(date(2025, 1, 11))
    assert closed.stage is NcrStage.CLOSED
    assert closed.suspect_from == date(2024, 10, 1)


def test_a_bath_report_needs_no_window() -> None:
    report = (
        ncr(subject=NcrSubject.BATH, reference="QT-1")
        .disposition_as(Disposition.REVIEW, date(2025, 1, 9))
        .action(date(2025, 1, 10), "bath drained and recharged")
    )
    assert report.close(date(2025, 1, 11)).stage is NcrStage.CLOSED


def test_voiding_works_from_any_open_stage() -> None:
    assert ncr().void("raised in error").stage is NcrStage.VOIDED
    dispositioned = ncr().disposition_as(Disposition.REWORK, date(2025, 1, 9))
    assert dispositioned.void("duplicate").stage is NcrStage.VOIDED


def test_a_finished_report_cannot_be_voided() -> None:
    closed = (
        ncr()
        .disposition_as(Disposition.REWORK, date(2025, 1, 9))
        .action(date(2025, 1, 10), "rerun")
        .close(date(2025, 1, 11))
    )
    with pytest.raises(StateError):
        closed.void("too late")


def test_voiding_needs_a_reason() -> None:
    with pytest.raises(ValidationError):
        ncr().void("  ")


def test_notes_accumulate() -> None:
    report = ncr().note("customer informed").note("awaiting concession")
    assert report.entries == ("customer informed", "awaiting concession")
    with pytest.raises(ValidationError):
        report.note("  ")


def test_age_counts_days() -> None:
    assert ncr().age(date(2025, 2, 1)) == 24
