"""Normalising an identifier before it reaches a query.

``TC-01`` and ``TC-00001`` are the same couple, ``ht-4`` and ``HT-04`` the same
furnace, and a caller typing the short form at a command line should not
silently miss the record. Every repository did this for itself, which meant four
copies of the same three lines and a fifth place that had quietly been left out.

Parsing is the normalisation. The tag types already know what a valid tag looks
like and how it is printed, so the canonical text is just ``str`` of the parsed
value, and an identifier that will not parse fails here rather than turning into
a query that matches nothing.
"""

from __future__ import annotations

from ..identity import FurnaceTag, InstrumentTag, LotNumber, SensorTag, WorkOrder


def furnace_key(value: FurnaceTag | str) -> str:
    """Canonical text for a furnace tag, however it was written."""
    return str(value) if isinstance(value, FurnaceTag) else str(FurnaceTag.parse(value))


def sensor_key(value: SensorTag | str) -> str:
    """Canonical text for a thermocouple tag, however it was written."""
    return str(value) if isinstance(value, SensorTag) else str(SensorTag.parse(value))


def instrument_key(value: InstrumentTag | str) -> str:
    """Canonical text for an instrument tag, however it was written."""
    if isinstance(value, InstrumentTag):
        return str(value)
    return str(InstrumentTag.parse(value))


def lot_key(value: LotNumber | str) -> str:
    """Canonical text for a lot number, however it was written."""
    return str(value) if isinstance(value, LotNumber) else str(LotNumber.parse(value))


def work_order_key(value: WorkOrder | str) -> str:
    """Canonical text for a work order, however it was written."""
    return str(value) if isinstance(value, WorkOrder) else str(WorkOrder.parse(value))
