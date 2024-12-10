from __future__ import annotations

import pytest

from quenchline.errors import OutOfRangeError, ValidationError
from quenchline.hardness.scales import Hardness, HardnessScale, convert


def test_scale_parsing() -> None:
    assert HardnessScale.parse("hrc") is HardnessScale.HRC
    assert HardnessScale.parse(" HBW ") is HardnessScale.HBW
    assert HardnessScale.parse("hr 15 n") is HardnessScale.HR15N
    with pytest.raises(ValidationError):
        HardnessScale.parse("mohs")


def test_scale_groups() -> None:
    assert HardnessScale.HRC.is_rockwell
    assert not HardnessScale.HBW.is_rockwell
    assert HardnessScale.HR15N.is_superficial
    assert not HardnessScale.HRC.is_superficial


def test_a_reading_outside_its_scale_is_refused() -> None:
    with pytest.raises(OutOfRangeError):
        Hardness(10.0, HardnessScale.HRC)
    with pytest.raises(OutOfRangeError):
        Hardness(75.0, HardnessScale.HRC)
    with pytest.raises(OutOfRangeError):
        Hardness(50.0, HardnessScale.HBW)


def test_the_scale_limits_are_inclusive() -> None:
    assert Hardness(20.0, HardnessScale.HRC).value == pytest.approx(20.0)
    assert Hardness(70.0, HardnessScale.HRC).value == pytest.approx(70.0)


def test_reading_parsing() -> None:
    assert Hardness.parse("45 HRC") == Hardness(45.0, HardnessScale.HRC)
    assert Hardness.parse("321HBW").scale is HardnessScale.HBW
    with pytest.raises(ValidationError):
        Hardness.parse("45")
    with pytest.raises(ValidationError):
        Hardness.parse("hardHRC")


def test_readings_compare_only_within_a_scale() -> None:
    assert Hardness(45.0, HardnessScale.HRC) > Hardness(40.0, HardnessScale.HRC)
    assert Hardness(40.0, HardnessScale.HRC) < Hardness(45.0, HardnessScale.HRC)
    assert Hardness(40.0, HardnessScale.HRC) <= Hardness(40.0, HardnessScale.HRC)
    assert Hardness(40.0, HardnessScale.HRC) >= Hardness(40.0, HardnessScale.HRC)
    with pytest.raises(ValidationError):
        _ = Hardness(45.0, HardnessScale.HRC) > Hardness(300.0, HardnessScale.HBW)


def test_formatting_marks_a_converted_value() -> None:
    assert str(Hardness(45.0, HardnessScale.HRC)) == "45 HRC"
    assert "(converted)" in str(Hardness(45.0, HardnessScale.HRC, converted=True))


def test_converting_to_the_same_scale_changes_nothing() -> None:
    reading = Hardness(45.0, HardnessScale.HRC)
    assert convert(reading, HardnessScale.HRC) is reading


def test_rockwell_c_to_vickers() -> None:
    converted = convert(Hardness(45.0, HardnessScale.HRC), HardnessScale.HV)
    assert converted.value == pytest.approx(446.0)
    assert converted.converted


def test_vickers_back_to_rockwell_c() -> None:
    converted = convert(Hardness(446.0, HardnessScale.HV), HardnessScale.HRC)
    assert converted.value == pytest.approx(45.0, abs=0.1)


def test_rockwell_c_to_brinell() -> None:
    converted = convert(Hardness(40.0, HardnessScale.HRC), HardnessScale.HBW)
    assert converted.value == pytest.approx(371.0)


def test_brinell_to_vickers_goes_through_rockwell_c() -> None:
    converted = convert(Hardness(371.0, HardnessScale.HBW), HardnessScale.HV)
    assert converted.value == pytest.approx(392.0, abs=1.0)


def test_rockwell_b_converts_only_at_the_top_of_its_range() -> None:
    converted = convert(Hardness(95.0, HardnessScale.HRB), HardnessScale.HRC)
    assert converted.value == pytest.approx(28.0)
    with pytest.raises(ValidationError):
        convert(Hardness(60.0, HardnessScale.HRB), HardnessScale.HRC)


def test_a_hard_reading_has_no_rockwell_b_equivalent() -> None:
    with pytest.raises(ValidationError):
        convert(Hardness(55.0, HardnessScale.HRC), HardnessScale.HRB)


def test_brinell_stops_before_the_hardest_steels() -> None:
    with pytest.raises(ValidationError):
        convert(Hardness(65.0, HardnessScale.HRC), HardnessScale.HBW)


def test_rockwell_a_converts_both_ways() -> None:
    to_a = convert(Hardness(50.0, HardnessScale.HRC), HardnessScale.HRA)
    assert to_a.value == pytest.approx(75.9, abs=0.1)
    back = convert(to_a, HardnessScale.HRC)
    assert back.value == pytest.approx(50.0, abs=0.2)


def test_superficial_rockwell_does_not_convert() -> None:
    with pytest.raises(ValidationError):
        convert(Hardness(90.0, HardnessScale.HR15N), HardnessScale.HRC)
    with pytest.raises(ValidationError):
        convert(Hardness(45.0, HardnessScale.HRC), HardnessScale.HR15N)


def test_a_converted_reading_stays_marked_after_a_second_conversion() -> None:
    once = convert(Hardness(45.0, HardnessScale.HRC), HardnessScale.HV)
    twice = convert(once, HardnessScale.HBW)
    assert twice.converted
