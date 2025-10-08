from __future__ import annotations

import pytest

from quenchline.errors import ParseError, ValidationError
from quenchline.identity import FurnaceTag, InstrumentTag, LotNumber, SensorTag, WorkOrder
from quenchline.store.keys import (
    furnace_key,
    instrument_key,
    lot_key,
    sensor_key,
    work_order_key,
)


def test_a_short_tag_becomes_the_canonical_one() -> None:
    assert furnace_key("ht-4") == "HT-04"
    assert sensor_key("tc-1") == "TC-00001"
    assert instrument_key("ic-4") == "IC-04"


def test_an_already_parsed_tag_passes_straight_through() -> None:
    assert furnace_key(FurnaceTag.parse("HT-04")) == "HT-04"
    assert sensor_key(SensorTag.parse("TC-01")) == "TC-00001"
    assert instrument_key(InstrumentTag.parse("IC-04")) == "IC-04"


def test_lot_and_work_order_keys() -> None:
    assert lot_key("l24-0917") == "L24-0917"
    assert lot_key(LotNumber.parse("L24-0917")) == "L24-0917"
    assert work_order_key("w104417") == "W104417"
    assert work_order_key(WorkOrder.parse("W104417-2")) == "W104417-2"


def test_an_identifier_that_will_not_parse_fails_here() -> None:
    for call, text in (
        (furnace_key, "nonsense"),
        (sensor_key, "nonsense"),
        (instrument_key, "nonsense"),
        (lot_key, "nonsense"),
        (work_order_key, "nonsense"),
    ):
        with pytest.raises(ParseError):
            call(text)


def test_the_wrong_prefix_is_refused_rather_than_matching_nothing() -> None:
    with pytest.raises(ValidationError):
        furnace_key("TC-01")
    with pytest.raises(ValidationError):
        sensor_key("HT-04")


def test_surrounding_noise_is_stripped() -> None:
    assert furnace_key("  ht - 04  ") == "HT-04"
    assert lot_key("  l24-0917 ") == "L24-0917"
