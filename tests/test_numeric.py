from __future__ import annotations

import pytest

from quenchline.errors import OutOfRangeError, ValidationError
from quenchline.numeric import (
    Curve,
    Extrapolation,
    mean,
    median,
    sample_stdev,
    slope,
    spread,
)

POINTS = [(600.0, 1.0), (1000.0, 2.0), (1600.0, -1.0)]


def build(extrapolation: Extrapolation = Extrapolation.REFUSE) -> Curve:
    return Curve.from_points(POINTS, extrapolation=extrapolation)


def test_curve_sorts_its_points() -> None:
    curve = Curve.from_points([(1600.0, -1.0), (600.0, 1.0), (1000.0, 2.0)])
    assert curve.xs == (600.0, 1000.0, 1600.0)
    assert curve.ys == (1.0, 2.0, -1.0)


def test_curve_reads_exactly_on_a_point() -> None:
    curve = build()
    assert curve.at(600.0) == pytest.approx(1.0)
    assert curve.at(1000.0) == pytest.approx(2.0)
    assert curve.at(1600.0) == pytest.approx(-1.0)


def test_curve_interpolates_between_points() -> None:
    curve = build()
    assert curve.at(800.0) == pytest.approx(1.5)
    assert curve.at(1300.0) == pytest.approx(0.5)


def test_curve_refuses_outside_its_range_by_default() -> None:
    curve = build()
    with pytest.raises(OutOfRangeError):
        curve.at(400.0)
    with pytest.raises(OutOfRangeError):
        curve.at(1800.0)


def test_curve_can_clamp_instead() -> None:
    curve = build(Extrapolation.CLAMP)
    assert curve.at(400.0) == pytest.approx(1.0)
    assert curve.at(1800.0) == pytest.approx(-1.0)


def test_curve_can_extrapolate_linearly() -> None:
    curve = build(Extrapolation.LINEAR)
    assert curve.at(400.0) == pytest.approx(0.5)
    assert curve.at(1900.0) == pytest.approx(-2.5)


def test_covers_and_bounds() -> None:
    curve = build()
    assert curve.low == pytest.approx(600.0)
    assert curve.high == pytest.approx(1600.0)
    assert curve.covers(1000.0)
    assert not curve.covers(500.0)


def test_curve_validation() -> None:
    with pytest.raises(ValidationError):
        Curve((600.0, 1000.0), (1.0,))
    with pytest.raises(ValidationError):
        Curve((600.0,), (1.0,))
    with pytest.raises(ValidationError):
        Curve((600.0, 600.0), (1.0, 2.0))


def test_shifted_moves_every_y() -> None:
    curve = build().shifted(0.5)
    assert curve.at(600.0) == pytest.approx(1.5)
    assert curve.at(1600.0) == pytest.approx(-0.5)


def test_mean_and_median() -> None:
    assert mean([1.0, 2.0, 6.0]) == pytest.approx(3.0)
    assert median([1.0, 2.0, 6.0]) == pytest.approx(2.0)
    assert median([1.0, 2.0, 6.0, 7.0]) == pytest.approx(4.0)


def test_spread_is_max_minus_min() -> None:
    assert spread([1545.0, 1552.0, 1548.0]) == pytest.approx(7.0)


def test_sample_stdev() -> None:
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert sample_stdev(values) == pytest.approx(2.13809, abs=1e-4)


def test_statistics_refuse_empty_input() -> None:
    with pytest.raises(ValidationError):
        mean([])
    with pytest.raises(ValidationError):
        median([])
    with pytest.raises(ValidationError):
        spread([])
    with pytest.raises(ValidationError):
        sample_stdev([1.0])


def test_slope_of_a_straight_line() -> None:
    assert slope([0.0, 1.0, 2.0, 3.0], [10.0, 12.0, 14.0, 16.0]) == pytest.approx(2.0)


def test_slope_of_a_falling_line() -> None:
    assert slope([0.0, 10.0], [1500.0, 500.0]) == pytest.approx(-100.0)


def test_slope_validation() -> None:
    with pytest.raises(ValidationError):
        slope([1.0], [1.0])
    with pytest.raises(ValidationError):
        slope([1.0, 2.0], [1.0])
    with pytest.raises(ValidationError):
        slope([1.0, 1.0], [1.0, 2.0])
