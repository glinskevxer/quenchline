from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ConflictError, NotFoundError
from quenchline.loads.disposition import Disposition
from quenchline.nonconformance.record import NcrStage, NcrSubject, Nonconformance
from quenchline.nonconformance.register import (
    NcrRegister,
    ageing_summary,
    register_table,
)

TODAY = date(2025, 2, 1)


def ncr(
    number: str,
    subject: NcrSubject = NcrSubject.LOAD,
    reference: str = "L24-0917",
    raised: date = date(2025, 1, 28),
) -> Nonconformance:
    return Nonconformance(number, subject, reference, raised, "something went wrong")


def register(*reports: Nonconformance) -> NcrRegister:
    reg = NcrRegister()
    for report in reports:
        reg.raise_report(report)
    return reg


def test_raise_get_and_conflict() -> None:
    reg = register(ncr("NCR-25-001"))
    assert len(reg) == 1
    assert "NCR-25-001" in reg
    assert reg.get("NCR-25-001").reference == "L24-0917"
    with pytest.raises(ConflictError):
        reg.raise_report(ncr("NCR-25-001"))
    with pytest.raises(NotFoundError):
        reg.get("NCR-25-999")


def test_update_replaces_the_report() -> None:
    reg = register(ncr("NCR-25-001"))
    moved = reg.get("NCR-25-001").disposition_as(Disposition.REWORK, date(2025, 1, 29))
    reg.update(moved)
    assert reg.get("NCR-25-001").stage is NcrStage.DISPOSITIONED
    with pytest.raises(NotFoundError):
        reg.update(ncr("NCR-25-999"))


def test_listing_helpers() -> None:
    reg = register(
        ncr("NCR-25-002", NcrSubject.INSTRUMENT, "IC-04"),
        ncr("NCR-25-001"),
    )
    assert [r.number for r in reg.all()] == ["NCR-25-001", "NCR-25-002"]
    assert [r.number for r in reg.about(NcrSubject.INSTRUMENT)] == ["NCR-25-002"]
    assert [r.number for r in reg.against("IC-04")] == ["NCR-25-002"]
    assert [r.number for r in reg.at_stage(NcrStage.RAISED)] == [
        "NCR-25-001",
        "NCR-25-002",
    ]


def test_open_reports_drop_the_closed_ones() -> None:
    reg = register(ncr("NCR-25-001"), ncr("NCR-25-002"))
    closed = (
        reg.get("NCR-25-002")
        .disposition_as(Disposition.REWORK, date(2025, 1, 29))
        .action(date(2025, 1, 30), "rerun")
        .close(date(2025, 1, 31))
    )
    reg.update(closed)
    assert [r.number for r in reg.open_reports()] == ["NCR-25-001"]


def test_older_than_only_counts_open_reports() -> None:
    reg = register(
        ncr("NCR-25-001", raised=date(2024, 10, 1)),
        ncr("NCR-25-002", raised=date(2025, 1, 30)),
    )
    assert [r.number for r in reg.older_than(30, TODAY)] == ["NCR-25-001"]
    assert reg.older_than(200, TODAY) == []


def test_ageing_buckets() -> None:
    reg = register(
        ncr("NCR-25-001", raised=date(2025, 1, 30)),
        ncr("NCR-25-002", raised=date(2025, 1, 10)),
        ncr("NCR-25-003", raised=date(2024, 12, 1)),
        ncr("NCR-25-004", raised=date(2024, 8, 1)),
    )
    buckets = reg.ageing(TODAY)
    assert buckets["under 7 days"] == 1
    assert buckets["over 7 days"] == 1
    assert buckets["over 30 days"] == 1
    assert buckets["over 90 days"] == 1


def test_ageing_of_an_empty_register_is_all_zeroes() -> None:
    buckets = NcrRegister().ageing(TODAY)
    assert set(buckets.values()) == {0}


def test_suspect_windows_are_collected() -> None:
    reg = register(ncr("NCR-25-001"), ncr("NCR-25-002", NcrSubject.INSTRUMENT, "IC-04"))
    reg.update(reg.get("NCR-25-002").with_suspect_window(date(2024, 10, 1), date(2025, 1, 28)))
    assert reg.suspect_windows() == [("NCR-25-002", date(2024, 10, 1), date(2025, 1, 28))]


def test_register_table_lists_everything() -> None:
    reg = register(ncr("NCR-25-001"))
    reg.update(reg.get("NCR-25-001").disposition_as(Disposition.SCRAP, date(2025, 1, 29)))
    table = register_table(reg, TODAY)
    rendered = table.render()
    assert "nonconformance register" in rendered
    assert "NCR-25-001" in rendered
    assert "scrap" in rendered
    assert table.rows[0][4] == 4


def test_register_table_shows_a_dash_before_a_disposition() -> None:
    table = register_table(register(ncr("NCR-25-001")), TODAY)
    assert table.rows[0][6] is None


def test_ageing_summary_reports_the_buckets() -> None:
    reg = register(ncr("NCR-25-001", raised=date(2024, 8, 1)))
    summary = ageing_summary(reg, TODAY)
    assert "nonconformance ageing" in summary
    assert "over 90 days  1" in summary
    assert "open          1" in summary
