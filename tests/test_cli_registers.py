from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from quenchline.cli.context import Context
from quenchline.cli.registers import (
    board,
    furnace_register,
    instrument_register,
    sat_histories,
    sensor_register,
)
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.furnaces.record import Furnace
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.sensors.record import Construction, SensorRole, Thermocouple
from quenchline.sensors.types import ThermocoupleType
from quenchline.sensors.usage import UsageEvent
from quenchline.temperature import Temperature
from quenchline.timespan import hours


@pytest.fixture()
def context(tmp_path: Path) -> Iterator[Context]:
    with Context.build(
        database=tmp_path / "shop.sqlite", today=date(2025, 9, 1), environ={}
    ) as built:
        yield built


def test_an_empty_shop_gives_empty_registers(context: Context) -> None:
    assert len(furnace_register(context)) == 0
    assert len(sensor_register(context)) == 0
    assert len(instrument_register(context)) == 0
    assert sat_histories(context) == []
    assert len(board(context)) == 0


def test_the_furnace_register_is_rebuilt(context: Context) -> None:
    context.shop().furnaces.insert(
        Furnace(
            tag=FurnaceTag.parse("HT-04"),
            furnace_class=FurnaceClass.CLASS_3,
            instrumentation=InstrumentationType.D,
        )
    )
    register = furnace_register(context)
    assert [str(f.tag) for f in register.all()] == ["HT-04"]


def test_the_sensor_register_carries_the_ledgers(context: Context) -> None:
    shop = context.shop()
    shop.sensors.insert(
        Thermocouple(
            tag=SensorTag.parse("TC-01"),
            kind=ThermocoupleType.K,
            construction=Construction.EXPENDABLE,
            role=SensorRole.LOAD,
        )
    )
    shop.sensors.record_use(
        "TC-01",
        UsageEvent(date(2025, 8, 1), Temperature.fahrenheit(1250), hours(2), SensorRole.LOAD),
    )
    register = sensor_register(context)
    assert register.ledger("TC-00001").uses == 1
    assert [str(c.tag) for c in register.spent()] == ["TC-00001"]


def test_a_register_built_without_the_ledgers_would_miss_the_spent_couple(
    context: Context,
) -> None:
    shop = context.shop()
    shop.sensors.insert(
        Thermocouple(
            tag=SensorTag.parse("TC-01"),
            kind=ThermocoupleType.K,
            construction=Construction.EXPENDABLE,
            role=SensorRole.LOAD,
        )
    )
    assert sensor_register(context).spent() == []


def test_the_sat_history_is_built_per_furnace(context: Context) -> None:
    context.shop().furnaces.insert(
        Furnace(
            tag=FurnaceTag.parse("HT-04"),
            furnace_class=FurnaceClass.CLASS_3,
            instrumentation=InstrumentationType.D,
        )
    )
    histories = sat_histories(context)
    assert len(histories) == 1
    assert histories[0].is_empty


def test_the_board_gathers_everything(context: Context) -> None:
    shop = context.shop()
    shop.furnaces.insert(
        Furnace(
            tag=FurnaceTag.parse("HT-04"),
            furnace_class=FurnaceClass.CLASS_3,
            instrumentation=InstrumentationType.D,
        )
    )
    shop.sensors.insert(
        Thermocouple(
            tag=SensorTag.parse("TC-01"),
            kind=ThermocoupleType.N,
            construction=Construction.NONEXPENDABLE,
            role=SensorRole.SURVEY,
        )
    )
    built = board(context)
    activities = {item.activity.value for item in built.items}
    assert "sensor_calibration" in activities
    assert "system_accuracy_test" in activities
