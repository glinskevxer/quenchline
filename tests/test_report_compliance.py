from __future__ import annotations

from datetime import date

import pytest

from quenchline.nonconformance.record import NcrSubject, Nonconformance
from quenchline.report.compliance import (
    Criterion,
    assess,
    summary_header,
    summary_table,
)
from quenchline.schedule.board import Board
from quenchline.schedule.policy import Activity, DueItem

TODAY = date(2025, 4, 1)


def item(activity: Activity, subject: str, due: date | None) -> DueItem:
    return DueItem.of(activity, subject, due, TODAY)


def board(*items: DueItem) -> Board:
    return Board(list(items))


def ncr(number: str, raised: date, open_report: bool = True) -> Nonconformance:
    report = Nonconformance(number, NcrSubject.LOAD, "L24-0917", raised, "soak short")
    if open_report:
        return report
    return report.void("raised in error")


def test_a_clean_shop_satisfies_everything() -> None:
    summary = assess(
        board(
            item(Activity.UNIFORMITY_SURVEY, "HT-04 main", date(2025, 9, 1)),
            item(Activity.SYSTEM_ACCURACY_TEST, "HT-04", date(2025, 6, 1)),
            item(Activity.INSTRUMENT_CALIBRATION, "IC-04", date(2025, 8, 1)),
            item(Activity.SENSOR_CALIBRATION, "TC-00001", date(2025, 8, 1)),
            item(Activity.BATH_CHECK, "QT-1", date(2025, 5, 1)),
        ),
        [],
        TODAY,
    )
    assert summary.satisfied
    assert summary.failures == ()
    assert summary.exception_count == 0


def test_every_criterion_is_reported_even_with_nothing_to_check() -> None:
    summary = assess(board(), [], TODAY)
    assert len(summary.findings) == len(Criterion)
    assert summary.satisfied


def test_an_overdue_survey_becomes_an_exception() -> None:
    summary = assess(
        board(item(Activity.UNIFORMITY_SURVEY, "HT-04 main", date(2024, 9, 1))),
        [],
        TODAY,
    )
    finding = summary.finding(Criterion.SURVEYS_IN_DATE)
    assert not finding.satisfied
    assert finding.exceptions == ("HT-04 main",)
    assert not summary.satisfied


def test_a_never_done_item_is_an_exception_too() -> None:
    summary = assess(board(item(Activity.SYSTEM_ACCURACY_TEST, "HT-11", None)), [], TODAY)
    assert not summary.finding(Criterion.ACCURACY_TESTS_IN_DATE).satisfied


def test_an_item_due_soon_is_not_an_exception() -> None:
    summary = assess(board(item(Activity.BATH_CHECK, "QT-1", date(2025, 4, 10))), [], TODAY)
    assert summary.finding(Criterion.BATHS_CHECKED).satisfied


def test_exceptions_are_sorted() -> None:
    summary = assess(
        board(
            item(Activity.INSTRUMENT_CALIBRATION, "IC-09", date(2024, 1, 1)),
            item(Activity.INSTRUMENT_CALIBRATION, "IC-04", date(2024, 1, 1)),
        ),
        [],
        TODAY,
    )
    assert summary.finding(Criterion.INSTRUMENTS_CALIBRATED).exceptions == (
        "IC-04",
        "IC-09",
    )


def test_one_criterion_failing_does_not_fail_the_others() -> None:
    summary = assess(
        board(
            item(Activity.UNIFORMITY_SURVEY, "HT-04 main", date(2024, 9, 1)),
            item(Activity.BATH_CHECK, "QT-1", date(2025, 5, 1)),
        ),
        [],
        TODAY,
    )
    assert not summary.finding(Criterion.SURVEYS_IN_DATE).satisfied
    assert summary.finding(Criterion.BATHS_CHECKED).satisfied


def test_an_old_open_report_is_an_exception() -> None:
    summary = assess(board(), [ncr("NCR-24-001", date(2024, 1, 1))], TODAY)
    finding = summary.finding(Criterion.NO_OVERDUE_NONCONFORMANCE)
    assert not finding.satisfied
    assert finding.exceptions == ("NCR-24-001",)


def test_a_recent_open_report_is_fine() -> None:
    summary = assess(board(), [ncr("NCR-25-001", date(2025, 3, 1))], TODAY)
    assert summary.finding(Criterion.NO_OVERDUE_NONCONFORMANCE).satisfied


def test_a_closed_report_is_never_an_exception() -> None:
    summary = assess(board(), [ncr("NCR-24-001", date(2024, 1, 1), open_report=False)], TODAY)
    assert summary.finding(Criterion.NO_OVERDUE_NONCONFORMANCE).satisfied


def test_the_age_limit_can_be_changed() -> None:
    reports = [ncr("NCR-25-001", date(2025, 2, 1))]
    assert assess(board(), reports, TODAY).satisfied
    assert not assess(board(), reports, TODAY, ncr_age_limit=30).satisfied


def test_finding_text() -> None:
    summary = assess(
        board(item(Activity.UNIFORMITY_SURVEY, "HT-04 main", date(2024, 9, 1))),
        [],
        TODAY,
    )
    assert "1 exception(s)" in str(summary.finding(Criterion.SURVEYS_IN_DATE))
    assert "satisfied" in str(summary.finding(Criterion.BATHS_CHECKED))


def test_an_unknown_criterion_raises() -> None:
    summary = assess(board(), [], TODAY)
    trimmed = type(summary)(summary.on, summary.findings[:1])
    with pytest.raises(KeyError):
        trimmed.finding(Criterion.BATHS_CHECKED)


def test_the_table_renders_a_row_per_criterion() -> None:
    summary = assess(board(), [], TODAY)
    table = summary_table(summary)
    assert len(table.rows) == len(Criterion)
    assert "compliance summary as of 2025-04-01" in table.render()


def test_the_header_counts_the_exceptions() -> None:
    summary = assess(
        board(item(Activity.UNIFORMITY_SURVEY, "HT-04 main", date(2024, 9, 1))),
        [],
        TODAY,
    )
    header = summary_header(summary)
    assert "exceptions  1" in header
    assert "overall     exception" in header
