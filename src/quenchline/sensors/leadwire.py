"""Extension wire and the cold junction.

A thermocouple only produces a voltage because its two junctions are at
different temperatures. The hot one is in the furnace. The cold one is wherever
the couple's wires meet ordinary copper, and every instrument has to know or
control that temperature to turn millivolts into degrees.

Two things go wrong on a shop floor and both are handled here.

**The wrong extension wire.** Extension wire has to be the same type as the
couple. Type K couple, type K extension. Somebody grabs a reel of type J
extension because it was nearer, and the reading is wrong by an amount that
depends on the temperature at the *joint*, not in the furnace, so it moves with
the weather and nobody can find it.

**A cold junction that is not where the instrument thinks it is.** An instrument
compensating for a 70 degF terminal block that is actually sitting at 110 degF
next to a quench tank reads 40 degrees low at every set point.

Both are modelled as an offset applied to the indicated reading, because that is
what they are, and both are worth being able to quantify when a system accuracy
test comes back with an error nobody can explain.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..numeric import Curve, Extrapolation
from ..temperature import Scale, Temperature, TemperatureDelta
from .types import ThermocoupleType

REFERENCE_JUNCTION = Temperature.fahrenheit(32.0)

# Approximate Seebeck coefficient near room temperature, microvolts per degF.
_SEEBECK_UV_PER_F: dict[str, float] = {
    "K": 22.8,
    "N": 14.6,
    "J": 28.9,
    "E": 34.2,
    "T": 21.4,
    "R": 3.3,
    "S": 3.3,
    "B": 0.1,
}


class WireGrade(Enum):
    """Extension wire is bought to one of two grades, like the couple itself."""

    EXTENSION = "extension"
    COMPENSATING = "compensating"


@dataclass(frozen=True)
class ExtensionWire:
    """A run of extension wire between a couple and its instrument."""

    kind: ThermocoupleType
    grade: WireGrade = WireGrade.EXTENSION
    identifier: str = ""

    def matches(self, couple_kind: ThermocoupleType) -> bool:
        return self.kind is couple_kind


@dataclass(frozen=True)
class MismatchError:
    """The error a mismatched extension wire introduces."""

    couple: ThermocoupleType
    wire: ThermocoupleType
    joint: Temperature
    error: TemperatureDelta

    @property
    def is_significant(self) -> bool:
        return abs(self.error.degf) >= 1.0


def mismatch_error(
    couple: ThermocoupleType,
    wire: ExtensionWire,
    joint: Temperature,
    instrument_reference: Temperature = REFERENCE_JUNCTION,
) -> MismatchError:
    """Estimate the error from running the wrong extension wire.

    The two wire types disagree only over the span between the joint and the
    instrument's reference junction, so a joint sitting exactly at the reference
    temperature produces no error at all however wrong the wire is. That is why
    the fault comes and goes with the seasons and why it is so hard to find.
    """
    span_f = joint.degf - instrument_reference.degf
    couple_uv = _SEEBECK_UV_PER_F[couple.value]
    wire_uv = _SEEBECK_UV_PER_F[wire.kind.value]
    if couple_uv == 0:
        raise ValidationError("this couple type has no usable sensitivity", field="couple")
    error_f = span_f * (wire_uv - couple_uv) / couple_uv
    return MismatchError(couple, wire.kind, joint, TemperatureDelta(error_f, Scale.FAHRENHEIT))


@dataclass(frozen=True)
class ColdJunction:
    """What the instrument believes about its terminal block, and what is true."""

    assumed: Temperature
    actual: Temperature

    @property
    def error(self) -> TemperatureDelta:
        """Signed error in the indicated reading.

        A terminal block hotter than the instrument assumes makes the reading
        low, so the error is negative.
        """
        return TemperatureDelta(self.assumed.degf - self.actual.degf, Scale.FAHRENHEIT)

    @property
    def is_compensated(self) -> bool:
        return abs(self.error.degf) < 0.5

    def correct(self, indicated: Temperature) -> Temperature:
        return indicated.minus(self.error)


def combined_offset(
    mismatch: MismatchError | None,
    junction: ColdJunction | None,
) -> TemperatureDelta:
    """Add up every offset the wiring is contributing."""
    total = 0.0
    if mismatch is not None:
        total += mismatch.error.degf
    if junction is not None:
        total += junction.error.degf
    return TemperatureDelta(total, Scale.FAHRENHEIT)


def sensitivity_curve(kind: ThermocoupleType) -> Curve:
    """A crude sensitivity curve, only used for sanity checks on raw millivolts."""
    base = _SEEBECK_UV_PER_F[kind.value]
    return Curve(
        (32.0, 1000.0, 2000.0),
        (base * 0.85, base, base * 1.05),
        Extrapolation.CLAMP,
    )
