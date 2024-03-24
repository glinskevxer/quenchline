from __future__ import annotations

import pytest

from quenchline.errors import ParseError, ValidationError
from quenchline.identity import (
    AssetTag,
    FurnaceTag,
    InstrumentTag,
    LotNumber,
    SensorTag,
    WorkOrder,
    normalise_code,
)


def test_normalise_upper_cases_and_strips() -> None:
    assert normalise_code("  ht-04 ") == "HT-04"
    assert normalise_code("tc 01188") == "TC01188"


def test_asset_tag_parses_and_prints() -> None:
    tag = FurnaceTag.parse("ht-4")
    assert tag.prefix == "HT"
    assert tag.serial == 4
    assert str(tag) == "HT-04"


def test_thermocouple_tags_print_five_digits() -> None:
    tag = SensorTag.parse("TC-1188")
    assert str(tag) == "TC-01188"


def test_a_trailing_letter_is_kept() -> None:
    tag = FurnaceTag.parse("HT-04A")
    assert tag.suffix == "A"
    assert str(tag) == "HT-04A"


def test_a_missing_leading_zero_is_not_invented_back_into_the_serial() -> None:
    assert SensorTag.parse("TC-118").serial == 118
    assert SensorTag.parse("TC-0118").serial == 118
    assert SensorTag.parse("TC-118") == SensorTag.parse("TC-0118")


def test_prefix_is_enforced_per_subclass() -> None:
    with pytest.raises(ValidationError):
        FurnaceTag.parse("TC-01188")
    with pytest.raises(ValidationError):
        SensorTag.parse("HT-04")
    with pytest.raises(ValidationError):
        InstrumentTag.parse("HT-04")


def test_the_base_tag_accepts_any_prefix() -> None:
    assert AssetTag.parse("ZZ-9").prefix == "ZZ"


def test_bad_tags_are_refused() -> None:
    for text in ("", "HT", "HT-", "-04", "HTHTH-04", "HT-1234567"):
        with pytest.raises(ParseError):
            FurnaceTag.parse(text)


def test_negative_serial_is_refused() -> None:
    with pytest.raises(ValidationError):
        FurnaceTag("HT", -1)


def test_tags_sort_by_prefix_then_serial() -> None:
    tags = [FurnaceTag.parse("HT-10"), FurnaceTag.parse("HT-02"), FurnaceTag.parse("QT-01")]
    assert [str(t) for t in sorted(tags)] == ["HT-02", "HT-10", "QT-01"]


def test_lot_number_round_trips() -> None:
    lot = LotNumber.parse("l24-0917")
    assert lot.year == 24
    assert lot.serial == 917
    assert str(lot) == "L24-0917"


def test_lot_number_increments() -> None:
    assert str(LotNumber(24, 917).next()) == "L24-0918"


def test_lot_number_rollover_is_an_error() -> None:
    with pytest.raises(ValidationError):
        LotNumber(24, 9999).next()


def test_lot_number_bounds() -> None:
    with pytest.raises(ValidationError):
        LotNumber(100, 1)
    with pytest.raises(ValidationError):
        LotNumber(24, 10000)
    with pytest.raises(ParseError):
        LotNumber.parse("L2024-0917")


def test_work_order_without_a_split() -> None:
    wo = WorkOrder.parse("w104417")
    assert wo.serial == 104417
    assert wo.split is None
    assert not wo.is_split
    assert str(wo) == "W104417"


def test_work_order_with_a_split() -> None:
    wo = WorkOrder.parse("W104417-2")
    assert wo.is_split
    assert wo.split == 2
    assert str(wo) == "W104417-2"
    assert str(wo.base()) == "W104417"
    assert str(wo.base().part(3)) == "W104417-3"


def test_work_order_bounds() -> None:
    with pytest.raises(ValidationError):
        WorkOrder(1000000)
    with pytest.raises(ValidationError):
        WorkOrder(1, 0)
    with pytest.raises(ParseError):
        WorkOrder.parse("104417")
