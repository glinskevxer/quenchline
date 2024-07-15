"""The system accuracy test, as a record.

A SAT asks one question: does the furnace's own measuring system tell the truth?
A technician puts a calibrated test sensor next to the furnace's control sensor,
reads both at the same moment, and compares.

Each side of that comparison is three numbers, not one:

* what the instrument displayed;
* the **sensor** correction from its calibration certificate;
* the **instrument** correction from its calibration record.

Both corrections have to be applied to both sides. Applying them to the test
side only is the common shortcut, and it hides exactly the fault a SAT exists to
find, because a drifting control sensor and a drifting control instrument can
cancel on the display and still be two failures.

Whether corrections are applied at all is a shop policy, and it is not free. A
shop that does not apply them accepts a tighter tolerance in exchange, because
the uncorrected reading carries the correction as unmeasured error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..errors import ValidationError
from ..identity import FurnaceTag, InstrumentTag, SensorTag
from ..temperature import Scale, Temperature, TemperatureDelta


class SatMethod(Enum):
    """How the test was carried out."""

    PROBE = "probe"
    ALTERNATE = "alternate"

    @property
    def needs_a_test_sensor(self) -> bool:
        return self is SatMethod.PROBE


@dataclass(frozen=True)
class SatReading:
    """One side of the comparison: what was displayed and what it really was."""

    indicated: Temperature
    sensor_correction: TemperatureDelta
    instrument_correction: TemperatureDelta
    sensor: SensorTag | None = None
    instrument: InstrumentTag | None = None

    @property
    def total_correction(self) -> TemperatureDelta:
        return TemperatureDelta(
            self.sensor_correction.degf + self.instrument_correction.degf, Scale.FAHRENHEIT
        )

    def corrected(self) -> Temperature:
        return self.indicated + self.total_correction

    def value(self, *, apply_corrections: bool) -> Temperature:
        return self.corrected() if apply_corrections else self.indicated


@dataclass(frozen=True)
class SatTest:
    """One system accuracy test on one furnace sensor system."""

    number: str
    furnace: FurnaceTag
    performed: date
    setpoint: Temperature
    system: SatReading
    test: SatReading
    method: SatMethod = SatMethod.PROBE
    technician: str = ""
    apply_corrections: bool = True

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("test number is blank", field="number")
        if self.method.needs_a_test_sensor and self.test.sensor is None:
            raise ValidationError(
                "a probe method test needs the test sensor identified", field="test"
            )

    @property
    def system_value(self) -> Temperature:
        return self.system.value(apply_corrections=self.apply_corrections)

    @property
    def test_value(self) -> Temperature:
        return self.test.value(apply_corrections=self.apply_corrections)

    @property
    def difference(self) -> TemperatureDelta:
        """System minus test. Positive means the furnace reads high."""
        return self.system_value.difference(self.test_value)

    @property
    def reads_high(self) -> bool:
        return self.difference.degf > 0

    @property
    def offset_from_setpoint(self) -> TemperatureDelta:
        return self.test_value.difference(self.setpoint)

    def with_corrections(self, *, apply_corrections: bool) -> SatTest:
        """The same test read under the other correction policy."""
        return SatTest(
            self.number,
            self.furnace,
            self.performed,
            self.setpoint,
            self.system,
            self.test,
            self.method,
            self.technician,
            apply_corrections,
        )

    def __str__(self) -> str:
        return f"{self.number} on {self.furnace} at {self.setpoint.format()}"
