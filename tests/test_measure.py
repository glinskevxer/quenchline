from __future__ import annotations

import pytest

from quenchline.errors import ParseError, ValidationError
from quenchline.measure import Length, LengthUnit, Mass, MassUnit, Volume


def test_mass_unit_spellings() -> None:
    for text in ("lb", "LBS", "pounds", "#"):
        assert MassUnit.parse(text) is MassUnit.POUND
    for text in ("kg", "Kilograms", "kilo"):
        assert MassUnit.parse(text) is MassUnit.KILOGRAM


def test_mass_unit_rejects_tons() -> None:
    with pytest.raises(ParseError):
        MassUnit.parse("ton")


def test_mass_converts_both_ways() -> None:
    assert Mass.kilograms(100).pounds_value == pytest.approx(220.462, abs=1e-3)
    assert Mass.pounds(2204.62).to(MassUnit.KILOGRAM).value == pytest.approx(1000.0, abs=1e-2)


def test_mass_to_its_own_unit_is_the_same_object() -> None:
    m = Mass.pounds(500)
    assert m.to(MassUnit.POUND) is m


def test_negative_mass_is_refused() -> None:
    with pytest.raises(ValidationError):
        Mass.pounds(-1)


def test_mass_parsing() -> None:
    assert Mass.parse("1450 lb") == Mass.pounds(1450)
    assert Mass.parse("658kg").unit is MassUnit.KILOGRAM
    assert Mass.parse("1450", default_unit=MassUnit.POUND).value == pytest.approx(1450.0)


def test_mass_parsing_without_a_unit_or_default_is_refused() -> None:
    with pytest.raises(ParseError):
        Mass.parse("1450")
    with pytest.raises(ParseError):
        Mass.parse("heavy")


def test_mass_arithmetic_and_ordering() -> None:
    assert (Mass.pounds(100) + Mass.kilograms(10)).value == pytest.approx(122.046, abs=1e-3)
    assert (Mass.pounds(100) * 3).value == pytest.approx(300.0)
    assert Mass.kilograms(50) > Mass.pounds(100)
    assert Mass.pounds(100) < Mass.kilograms(50)
    assert Mass.pounds(100) <= Mass.pounds(100)
    assert Mass.pounds(100) >= Mass.pounds(100)


def test_mass_formatting() -> None:
    assert str(Mass.pounds(1450)) == "1450.0 lb"


def test_length_unit_spellings() -> None:
    assert LengthUnit.parse("inches") is LengthUnit.INCH
    assert LengthUnit.parse("MM") is LengthUnit.MILLIMETRE
    with pytest.raises(ParseError):
        LengthUnit.parse("furlong")


def test_length_converts() -> None:
    assert Length.inches(1).to(LengthUnit.MILLIMETRE).value == pytest.approx(25.4)
    assert Length.millimetres(254).inches_value == pytest.approx(10.0)


def test_negative_length_is_refused() -> None:
    with pytest.raises(ValidationError):
        Length.inches(-2)


def test_length_ordering_and_formatting() -> None:
    assert Length.inches(12) > Length.millimetres(300)
    assert Length.millimetres(300) < Length.inches(12)
    assert str(Length.inches(12)) == "12.00 in"


def test_volume_from_a_box_in_inches() -> None:
    volume = Volume.from_box(Length.inches(24), Length.inches(24), Length.inches(36))
    assert volume.cubic_feet == pytest.approx(12.0)


def test_volume_from_a_box_in_millimetres() -> None:
    side = Length.millimetres(1000)
    volume = Volume.from_box(side, side, side)
    assert volume.cubic_feet == pytest.approx(35.3147, abs=1e-3)


def test_volume_from_cubic_metres_round_trips() -> None:
    volume = Volume.cubic_metres(2.0)
    assert volume.cubic_feet == pytest.approx(70.629, abs=1e-3)
    assert volume.cubic_metres_value == pytest.approx(2.0)


def test_negative_volume_is_refused() -> None:
    with pytest.raises(ValidationError):
        Volume(-1.0)


def test_volume_ordering_and_formatting() -> None:
    assert Volume(20.0) > Volume(10.0)
    assert Volume(10.0) < Volume(20.0)
    assert str(Volume(12.0)) == "12.0 cuft"
