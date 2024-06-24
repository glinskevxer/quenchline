"""Furnaces: their class, their instrumentation and their qualified range."""

from .classes import (
    FurnaceClass,
    InstrumentationType,
    sat_interval,
    sensor_requirements,
    tus_interval,
    uniformity_tolerance,
)

__all__ = [
    "FurnaceClass",
    "InstrumentationType",
    "sat_interval",
    "sensor_requirements",
    "tus_interval",
    "uniformity_tolerance",
]
