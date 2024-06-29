from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.furnaces.classes import FurnaceClass
from quenchline.furnaces.zones import (
    QualifiedRange,
    WorkZone,
    base_sensor_count,
    survey_sensor_count,
)
from quenchline.measure import Volume
from quenchline.temperature import Temperature


def zone(cubic_feet: float = 40.0) -> WorkZone:
    return WorkZone(
        "main",
        Volume(cubic_feet),
        Temperature.fahrenheit(1000),
        Temperature.fahrenheit(1800),
    )


def test_zone_validation() -> None:
    with pytest.raises(ValidationError):
        WorkZone(" ", Volume(10), Temperature.fahrenheit(1000), Temperature.fahrenheit(1800))
    with pytest.raises(ValidationError):
        WorkZone("main", Volume(0), Temperature.fahrenheit(1000), Temperature.fahrenheit(1800))
    with pytest.raises(ValidationError):
        WorkZone("main", Volume(10), Temperature.fahrenheit(1800), Temperature.fahrenheit(1000))


def test_zone_coverage_and_formatting() -> None:
    z = zone()
    assert z.covers(Temperature.fahrenheit(1550))
    assert z.covers(Temperature.fahrenheit(1000))
    assert not z.covers(Temperature.fahrenheit(1900))
    assert str(z) == "main (40.0 cuft)"
    assert not z.is_small
    assert zone(2.0).is_small


def test_small_zones_take_five_sensors() -> None:
    assert base_sensor_count(Volume(1.0)) == 5
    assert base_sensor_count(Volume(3.0)) == 5


def test_just_over_the_small_threshold_jumps_to_nine() -> None:
    assert base_sensor_count(Volume(3.01)) == 9


def test_the_nine_sensor_band_is_wide() -> None:
    assert base_sensor_count(Volume(50.0)) == 9
    assert base_sensor_count(Volume(225.0)) == 9


def test_past_the_band_one_sensor_per_further_step() -> None:
    assert base_sensor_count(Volume(226.0)) == 10
    assert base_sensor_count(Volume(350.0)) == 10
    assert base_sensor_count(Volume(351.0)) == 11


def test_the_sensor_count_is_capped() -> None:
    assert base_sensor_count(Volume(100000.0)) == 40


def test_a_zero_volume_is_refused() -> None:
    with pytest.raises(ValidationError):
        base_sensor_count(Volume(0.0))


def test_a_precision_furnace_carries_two_extra() -> None:
    assert survey_sensor_count(Volume(40.0), FurnaceClass.CLASS_1) == 11
    assert survey_sensor_count(Volume(40.0), FurnaceClass.CLASS_2) == 11
    assert survey_sensor_count(Volume(40.0), FurnaceClass.CLASS_3) == 9


def test_the_extra_sensors_do_not_break_the_ceiling() -> None:
    assert survey_sensor_count(Volume(100000.0), FurnaceClass.CLASS_1) == 40


def test_a_qualified_range_is_earned_from_survey_points() -> None:
    qualified = QualifiedRange.spanning(
        [Temperature.fahrenheit(1200), Temperature.fahrenheit(1700)]
    )
    assert qualified.low.degf == pytest.approx(1200.0)
    assert qualified.high.degf == pytest.approx(1700.0)
    assert qualified.width_f == pytest.approx(500.0)


def test_a_qualified_range_does_not_reach_past_its_evidence() -> None:
    qualified = QualifiedRange.spanning(
        [Temperature.fahrenheit(1200), Temperature.fahrenheit(1700)]
    )
    assert qualified.covers(Temperature.fahrenheit(1700))
    assert not qualified.covers(Temperature.fahrenheit(1701))
    assert not qualified.covers(Temperature.fahrenheit(1199))


def test_a_single_point_range() -> None:
    qualified = QualifiedRange.single(Temperature.fahrenheit(1550))
    assert qualified.is_single_point
    assert str(qualified) == "1550 F only"
    assert qualified.covers(Temperature.fahrenheit(1550))


def test_spanning_needs_at_least_one_point() -> None:
    with pytest.raises(ValidationError):
        QualifiedRange.spanning([])


def test_an_inverted_range_is_refused() -> None:
    with pytest.raises(ValidationError):
        QualifiedRange(Temperature.fahrenheit(1700), Temperature.fahrenheit(1200))


def test_extending_widens_in_the_right_direction() -> None:
    qualified = QualifiedRange.single(Temperature.fahrenheit(1550))
    wider = qualified.extended_to(Temperature.fahrenheit(1700))
    assert wider.high.degf == pytest.approx(1700.0)
    assert wider.low.degf == pytest.approx(1550.0)
    lower = wider.extended_to(Temperature.fahrenheit(1200))
    assert lower.low.degf == pytest.approx(1200.0)


def test_extending_inside_the_range_changes_nothing() -> None:
    qualified = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1700))
    assert qualified.extended_to(Temperature.fahrenheit(1500)) == qualified


def test_narrowing_takes_the_overlap() -> None:
    a = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1700))
    b = QualifiedRange(Temperature.fahrenheit(1400), Temperature.fahrenheit(1900))
    overlap = a.narrowed_to(b)
    assert overlap.low.degf == pytest.approx(1400.0)
    assert overlap.high.degf == pytest.approx(1700.0)


def test_narrowing_disjoint_ranges_is_refused() -> None:
    a = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1300))
    b = QualifiedRange(Temperature.fahrenheit(1400), Temperature.fahrenheit(1900))
    with pytest.raises(ValidationError):
        a.narrowed_to(b)


def test_range_formatting() -> None:
    qualified = QualifiedRange(Temperature.fahrenheit(1200), Temperature.fahrenheit(1700))
    assert str(qualified) == "1200 F to 1700 F"
