from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import pytest

from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.furnaces.record import Furnace
from quenchline.identity import FurnaceTag, LotNumber, WorkOrder
from quenchline.loads.record import Load, LoadState, PartLine
from quenchline.nonconformance.record import NcrSubject, Nonconformance
from quenchline.store.shop import Shop


@pytest.fixture()
def shop() -> Iterator[Shop]:
    with Shop.in_memory() as opened:
        yield opened


def load(lot: str, state: LoadState, finished: datetime | None) -> Load:
    return Load(
        lot=LotNumber.parse(lot),
        work_order=WorkOrder.parse("W104417"),
        furnace=FurnaceTag.parse("HT-04"),
        recipe_code="HT-4140-Q",
        recipe_revision="C",
        parts=(PartLine("PN-8891", 10),),
        state=state,
        finished_at=finished,
    )


def ncr(number: str, start: date | None = None, end: date | None = None) -> Nonconformance:
    report = Nonconformance(
        number, NcrSubject.INSTRUMENT, "IC-04", date(2025, 1, 8), "found out of tolerance"
    )
    if start is not None and end is not None:
        report = report.with_suspect_window(start, end)
    return report


def test_the_shop_opens_a_file(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Shop.open(path) as shop:
        assert shop.database.version > 0
    assert path.exists()


def test_every_repository_is_wired_to_the_same_database(shop: Shop) -> None:
    assert shop.furnaces.database is shop.database
    assert shop.sensors.database is shop.database
    assert shop.loads.database is shop.database
    assert shop.reports.database is shop.database


def test_on_the_floor_is_charged_and_running(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.CHARGED, None))
    shop.loads.insert(load("L24-0918", LoadState.RUNNING, None))
    shop.loads.insert(load("L24-0919", LoadState.PLANNED, None))
    shop.loads.insert(load("L24-0920", LoadState.CERTIFIED, datetime(2024, 11, 4, 12)))
    assert [str(item.lot) for item in shop.on_the_floor()] == ["L24-0917", "L24-0918"]


def test_awaiting_disposition_is_complete_and_held(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.COMPLETE, datetime(2024, 11, 4, 12)))
    shop.loads.insert(load("L24-0918", LoadState.HELD, None))
    shop.loads.insert(load("L24-0919", LoadState.CERTIFIED, datetime(2024, 11, 5, 12)))
    lots = {str(item.lot) for item in shop.awaiting_disposition()}
    assert lots == {"L24-0917", "L24-0918"}


def test_furnace_history_lists_what_ran_there(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.CERTIFIED, datetime(2024, 11, 4, 12)))
    assert len(shop.furnace_history("HT-04")) == 1
    assert shop.furnace_history("HT-11") == []


def test_loads_in_doubt_uses_the_suspect_window(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.CERTIFIED, datetime(2024, 11, 4, 12)))
    shop.loads.insert(load("L24-0918", LoadState.CERTIFIED, datetime(2025, 2, 4, 12)))
    report = ncr("NCR-25-001", date(2024, 10, 1), date(2025, 1, 8))
    caught = shop.loads_in_doubt(report)
    assert [str(item.lot) for item in caught] == ["L24-0917"]


def test_the_window_is_inclusive_at_both_ends(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.CERTIFIED, datetime(2024, 10, 1, 0, 0)))
    shop.loads.insert(load("L24-0918", LoadState.CERTIFIED, datetime(2025, 1, 8, 23, 59)))
    report = ncr("NCR-25-001", date(2024, 10, 1), date(2025, 1, 8))
    assert len(shop.loads_in_doubt(report)) == 2


def test_a_report_with_no_window_catches_nothing(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.CERTIFIED, datetime(2024, 11, 4, 12)))
    assert shop.loads_in_doubt(ncr("NCR-25-001")) == []


def test_all_loads_in_doubt_covers_the_open_reports(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.CERTIFIED, datetime(2024, 11, 4, 12)))
    shop.reports.insert(ncr("NCR-25-001", date(2024, 10, 1), date(2025, 1, 8)))
    shop.reports.insert(ncr("NCR-25-002"))
    caught = shop.all_loads_in_doubt()
    assert set(caught) == {"NCR-25-001"}
    assert [str(item.lot) for item in caught["NCR-25-001"]] == ["L24-0917"]


def test_reports_against_a_furnace(shop: Shop) -> None:
    report = Nonconformance(
        "NCR-25-003", NcrSubject.FURNACE, "HT-04", date(2025, 1, 8), "survey overdue"
    )
    shop.reports.insert(report)
    assert [r.number for r in shop.reports_against_furnace("HT-04")] == ["NCR-25-003"]


def test_counts_cover_every_table(shop: Shop) -> None:
    shop.furnaces.insert(
        Furnace(
            tag=FurnaceTag.parse("HT-04"),
            furnace_class=FurnaceClass.CLASS_3,
            instrumentation=InstrumentationType.D,
        )
    )
    shop.loads.insert(load("L24-0917", LoadState.CERTIFIED, datetime(2024, 11, 4, 12)))
    shop.reports.insert(ncr("NCR-25-001"))
    counts = shop.counts()
    assert counts["furnaces"] == 1
    assert counts["loads"] == 1
    assert counts["pieces"] == 10
    assert counts["nonconformances"] == 1
    assert counts["thermocouples"] == 0
    assert shop.open_ncr_count() == 1


def test_certified_between_only_counts_certified_loads(shop: Shop) -> None:
    shop.loads.insert(load("L24-0917", LoadState.CERTIFIED, datetime(2024, 11, 4, 12)))
    shop.loads.insert(load("L24-0918", LoadState.REJECTED, datetime(2024, 11, 5, 12)))
    window = shop.certified_between(date(2024, 11, 1), date(2024, 11, 30))
    assert [str(item.lot) for item in window] == ["L24-0917"]


def test_an_empty_shop_reports_zeroes(shop: Shop) -> None:
    assert set(shop.counts().values()) == {0}
    assert shop.on_the_floor() == []
    assert shop.all_loads_in_doubt() == {}


def test_the_shop_wires_the_sat_repository(shop: Shop) -> None:
    assert shop.sat.database is shop.database
    assert shop.counts()["accuracy tests"] == 0


def test_the_shop_wires_the_recipe_and_bath_repositories(shop: Shop) -> None:
    assert shop.recipes.database is shop.database
    assert shop.baths.database is shop.database
    counts = shop.counts()
    assert counts["recipe revisions"] == 0
    assert counts["quench baths"] == 0


def test_the_shop_wires_the_instrument_repository(shop: Shop) -> None:
    assert shop.instruments.database is shop.database
    assert shop.counts()["instruments"] == 0
