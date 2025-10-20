"""quenchline: pyrometry and process records for a heat treating shop.

The names re-exported here are the ones every other module in the package uses.
Anything more specialised is imported from its own module.
"""

from .calendar_rules import DueRule, Interval
from .errors import (
    ConflictError,
    NotFoundError,
    OutOfRangeError,
    ParseError,
    QuenchlineError,
    StateError,
    ValidationError,
)
from .identity import FurnaceTag, InstrumentTag, LotNumber, SensorTag, WorkOrder
from .temperature import Scale, Temperature, TemperatureDelta, degc, degf, round_temperature
from .timespan import Duration, hours, minutes
from .tolerance import Band, Position

__version__ = "1.0.0"

__all__ = [
    "Band",
    "ConflictError",
    "DueRule",
    "Duration",
    "FurnaceTag",
    "InstrumentTag",
    "Interval",
    "LotNumber",
    "NotFoundError",
    "OutOfRangeError",
    "ParseError",
    "Position",
    "QuenchlineError",
    "Scale",
    "SensorTag",
    "StateError",
    "Temperature",
    "TemperatureDelta",
    "ValidationError",
    "WorkOrder",
    "__version__",
    "degc",
    "degf",
    "hours",
    "minutes",
    "round_temperature",
]
