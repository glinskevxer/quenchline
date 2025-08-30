"""Rebuilding the in memory registers from the store.

Four commands were each building the same three registers out of the same
repositories, in the same order, with the same easily forgotten step: a sensor
register is not just its couples, it is its couples **and their usage ledgers**,
and a register built without the ledgers quietly reports every couple as brand
new.

That is exactly the sort of thing that is right in three places and wrong in the
fourth, so it lives here once.
"""

from __future__ import annotations

from ..furnaces.register import FurnaceRegister
from ..instruments.register import InstrumentRegister
from ..sat.schedule import SatHistory
from ..schedule.board import Board
from ..sensors.register import SensorRegister
from .context import Context


def furnace_register(context: Context) -> FurnaceRegister:
    register = FurnaceRegister()
    for furnace in context.shop().furnaces.all():
        register.add(furnace)
    return register


def sensor_register(context: Context) -> SensorRegister:
    """Every couple with the ledger that decides how much life it has left."""
    shop = context.shop()
    register = SensorRegister()
    for couple in shop.sensors.all():
        register.add(couple)
        register.ledgers[str(couple.tag)] = shop.sensors.ledger(couple.tag)
    return register


def instrument_register(context: Context) -> InstrumentRegister:
    return context.shop().instruments.register()


def sat_histories(context: Context) -> list[SatHistory]:
    """A judged system accuracy history per furnace on the register."""
    shop = context.shop()
    return [
        shop.sat.history(furnace.tag, furnace.furnace_class, furnace.instrumentation)
        for furnace in shop.furnaces.all()
    ]


def board(context: Context, grace: int = 0) -> Board:
    """Everything due, gathered from every register that holds a date."""
    shop = context.shop()
    return Board.build(
        context.today,
        instruments=instrument_register(context),
        sensors=sensor_register(context),
        sat=sat_histories(context),
        baths=shop.baths.all(),
        grace=grace,
    )
