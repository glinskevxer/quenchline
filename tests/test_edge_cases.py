"""The inputs that arrive when somebody is having a bad day.

Every value in this package comes in as text at some point: typed at a command
line, pasted from a spreadsheet, or read out of a file a logger wrote while it
was losing power. These are the shapes that text takes when it is wrong, kept in
one place because they are the same shapes for every type and it is easy to
harden one parser and forget the other five.
"""

from __future__ import annotations

import math

import pytest

from quenchline.errors import OutOfRangeError, ParseError, ValidationError
from quenchline.hardness.scales import Hardness, HardnessScale
from quenchline.identity import LotNumber, SensorTag, WorkOrder
from quenchline.measure import Length, Mass, MassUnit, Volume
from quenchline.numeric import require_finite
from quenchline.temperature import Scale, Temperature, TemperatureDelta
from quenchline.timespan import Duration
from quenchline.tolerance import Band

NOT_A_NUMBER = float("nan")
INFINITE = float("inf")


def test_require_finite_lets_a_real_number_through() -> None:
    assert require_finite(1550.0, "temperature") == pytest.approx(1550.0)
    assert require_finite(-40.0, "temperature") == pytest.approx(-40.0)


def test_require_finite_refuses_nan_and_infinity() -> None:
    with pytest.raises(ValidationError):
        require_finite(NOT_A_NUMBER, "temperature")
    with pytest.raises(ValidationError):
        require_finite(INFINITE, "temperature")
    with pytest.raises(ValidationError):
        require_finite(-INFINITE, "temperature")


def test_a_nan_temperature_is_refused() -> None:
    with pytest.raises(ValidationError):
        Temperature(NOT_A_NUMBER, Scale.FAHRENHEIT)
    with pytest.raises(ValidationError):
        Temperature(INFINITE, Scale.FAHRENHEIT)


def test_a_nan_delta_is_refused() -> None:
    with pytest.raises(ValidationError):
        TemperatureDelta(NOT_A_NUMBER, Scale.FAHRENHEIT)


def test_a_nan_duration_is_refused_rather_than_stored() -> None:
    with pytest.raises(ValidationError):
        Duration(NOT_A_NUMBER)
    with pytest.raises(ValidationError):
        Duration.parse("nan")


def test_an_infinite_duration_is_refused() -> None:
    with pytest.raises(ValidationError):
        Duration.parse("inf")


def test_a_nan_mass_length_or_volume_is_refused() -> None:
    with pytest.raises(ValidationError):
        Mass(NOT_A_NUMBER, MassUnit.POUND)
    with pytest.raises(ValidationError):
        Length.inches(NOT_A_NUMBER)
    with pytest.raises(ValidationError):
        Volume(NOT_A_NUMBER)


def test_temperature_parsing_refuses_the_usual_junk() -> None:
    for text in ("", "   ", "hot", "--5F", "1e5F", "1550 F extra", "F", "1550 K"):
        with pytest.raises(ParseError):
            Temperature.parse(text)


def test_temperature_parsing_still_takes_the_good_shapes() -> None:
    assert Temperature.parse("1550F").degf == pytest.approx(1550.0)
    assert Temperature.parse(" -40 degC ").degc == pytest.approx(-40.0)
    assert Temperature.parse(".5F").degf == pytest.approx(0.5)


def test_duration_parsing_refuses_the_usual_junk() -> None:
    for text in ("", "  ", "soon", "1:75", "-5", "1:2:3:4"):
        with pytest.raises((ParseError, ValidationError)):
            Duration.parse(text)


def test_a_very_large_duration_is_allowed_because_a_temper_can_be_days() -> None:
    assert Duration.parse("100000").hours > 1000


def test_mass_parsing_refuses_the_usual_junk() -> None:
    for text in ("", "heavy", "-5lb", "nan kg", "5 stone"):
        with pytest.raises((ParseError, ValidationError)):
            Mass.parse(text, default_unit=MassUnit.POUND)


def test_tag_parsing_refuses_the_usual_junk() -> None:
    for text in ("", "TC", "TC-", "-01", "TCTCT-01", "TC-1234567", "tc—01"):
        with pytest.raises(ParseError):
            SensorTag.parse(text)


def test_a_tag_with_surrounding_noise_still_parses() -> None:
    assert str(SensorTag.parse("  tc - 01  ")) == "TC-00001"


def test_lot_and_work_order_parsing_refuse_short_forms() -> None:
    for text in ("L24-091", "L2024-0917", "24-0917", ""):
        with pytest.raises(ParseError):
            LotNumber.parse(text)
    for text in ("W10441", "104417", "W1044170", ""):
        with pytest.raises(ParseError):
            WorkOrder.parse(text)


def test_hardness_parsing_refuses_impossible_readings() -> None:
    with pytest.raises(OutOfRangeError):
        Hardness.parse("nan HRC")
    with pytest.raises(OutOfRangeError):
        Hardness.parse("-45HRC")
    with pytest.raises(OutOfRangeError):
        Hardness(9999.0, HardnessScale.HV)


def test_a_band_of_zero_width_contains_only_its_setpoint() -> None:
    band = Band.symmetric(Temperature.fahrenheit(1550), TemperatureDelta(0.0, Scale.FAHRENHEIT))
    assert band.contains(Temperature.fahrenheit(1550))
    assert not band.contains(Temperature.fahrenheit(1550.5))
    assert band.width.magnitude == pytest.approx(0.0)


def test_a_very_wide_band_still_behaves() -> None:
    band = Band.symmetric(
        Temperature.fahrenheit(1550), TemperatureDelta(1000.0, Scale.FAHRENHEIT)
    )
    assert band.contains(Temperature.fahrenheit(600))
    assert not band.contains(Temperature.fahrenheit(2600))


def test_absolute_zero_is_the_floor_and_not_a_crash() -> None:
    assert Temperature.celsius(-273.15).degf == pytest.approx(-459.67, abs=1e-6)
    with pytest.raises(OutOfRangeError):
        Temperature.celsius(-273.16)


def test_arithmetic_never_produces_a_silent_nan() -> None:
    hot = Temperature.fahrenheit(2000)
    cold = Temperature.fahrenheit(-400)
    assert math.isfinite(hot.difference(cold).degf)
    assert math.isfinite((hot - cold).degf)
    assert math.isfinite(hot.midpoint(cold).degf)
