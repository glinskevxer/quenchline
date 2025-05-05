from __future__ import annotations

from datetime import date

import pytest

from quenchline.analysis.trend import (
    Direction,
    SurveyPoint,
    point,
    trend_of,
    worst_first,
)
from quenchline.errors import ValidationError
from quenchline.temperature import Scale, TemperatureDelta


def test_a_point_reports_the_fraction_of_band_used() -> None:
    p = point(date(2024, 1, 1), 7.5, 15.0)
    assert p.fraction == pytest.approx(0.5)


def test_the_sign_of_the_deviation_does_not_matter() -> None:
    assert point(date(2024, 1, 1), -7.5, 15.0).fraction == pytest.approx(0.5)


def test_a_zero_band_is_refused() -> None:
    with pytest.raises(ValidationError):
        SurveyPoint(
            date(2024, 1, 1),
            TemperatureDelta(7.5, Scale.FAHRENHEIT),
            TemperatureDelta(0.0, Scale.FAHRENHEIT),
        )


def test_two_surveys_are_not_a_trend() -> None:
    with pytest.raises(ValidationError):
        trend_of([point(date(2023, 1, 1), 5.0, 15.0), point(date(2024, 1, 1), 6.0, 15.0)])


def test_every_survey_on_the_same_day_is_refused() -> None:
    same = [point(date(2024, 1, 1), 5.0, 15.0) for _ in range(3)]
    with pytest.raises(ValidationError):
        trend_of(same)


def test_a_flat_furnace_is_steady() -> None:
    trend = trend_of(
        [
            point(date(2023, 1, 1), 7.5, 15.0),
            point(date(2023, 7, 1), 7.4, 15.0),
            point(date(2024, 1, 1), 7.6, 15.0),
        ]
    )
    assert trend.direction is Direction.STEADY
    assert not trend.is_worsening
    assert trend.crossing is None


def test_a_creeping_furnace_is_worsening() -> None:
    trend = trend_of(
        [
            point(date(2022, 1, 1), 4.5, 15.0),
            point(date(2023, 1, 1), 9.0, 15.0),
            point(date(2024, 1, 1), 13.5, 15.0),
        ]
    )
    assert trend.direction is Direction.WORSENING
    assert trend.per_year == pytest.approx(0.3, abs=0.02)
    assert trend.crossing is not None
    assert trend.crossing > date(2024, 1, 1)


def test_a_recovering_furnace_is_improving() -> None:
    trend = trend_of(
        [
            point(date(2022, 1, 1), 13.5, 15.0),
            point(date(2023, 1, 1), 9.0, 15.0),
            point(date(2024, 1, 1), 4.5, 15.0),
        ]
    )
    assert trend.direction is Direction.IMPROVING
    assert trend.crossing is None


def test_the_flat_threshold_can_be_tightened() -> None:
    points = [
        point(date(2022, 1, 1), 7.0, 15.0),
        point(date(2023, 1, 1), 7.5, 15.0),
        point(date(2024, 1, 1), 8.0, 15.0),
    ]
    assert trend_of(points).direction is Direction.STEADY
    assert trend_of(points, flat_per_year=0.01).direction is Direction.WORSENING


def test_a_zero_threshold_is_refused() -> None:
    points = [point(date(2022 + n, 1, 1), 7.0, 15.0) for n in range(3)]
    with pytest.raises(ValidationError):
        trend_of(points, flat_per_year=0.0)


def test_surveys_are_sorted_however_they_arrive() -> None:
    trend = trend_of(
        [
            point(date(2024, 1, 1), 13.5, 15.0),
            point(date(2022, 1, 1), 4.5, 15.0),
            point(date(2023, 1, 1), 9.0, 15.0),
        ]
    )
    assert trend.points[0].on == date(2022, 1, 1)
    assert trend.latest.on == date(2024, 1, 1)


def test_a_furnace_already_over_the_band_crosses_today() -> None:
    trend = trend_of(
        [
            point(date(2022, 1, 1), 5.0, 15.0),
            point(date(2023, 1, 1), 11.0, 15.0),
            point(date(2024, 1, 1), 16.0, 15.0),
        ]
    )
    assert trend.crossing == date(2024, 1, 1)


def test_the_average_fraction_is_reported() -> None:
    trend = trend_of(
        [
            point(date(2022, 1, 1), 3.0, 15.0),
            point(date(2023, 1, 1), 7.5, 15.0),
            point(date(2024, 1, 1), 12.0, 15.0),
        ]
    )
    assert trend.average_fraction == pytest.approx(0.5)


def test_trend_text_reports_the_direction_and_the_crossing() -> None:
    trend = trend_of(
        [
            point(date(2022, 1, 1), 4.5, 15.0),
            point(date(2023, 1, 1), 9.0, 15.0),
            point(date(2024, 1, 1), 13.5, 15.0),
        ]
    )
    text = str(trend)
    assert "worsening" in text
    assert "out of band around" in text


def test_worst_first_puts_the_deteriorating_furnaces_up_front() -> None:
    steady = trend_of([point(date(2022 + n, 1, 1), 14.0, 15.0) for n in range(3)])
    worsening = trend_of(
        [
            point(date(2022, 1, 1), 4.5, 15.0),
            point(date(2023, 1, 1), 9.0, 15.0),
            point(date(2024, 1, 1), 12.0, 15.0),
        ]
    )
    ordered = worst_first({"HT-04": steady, "HT-11": worsening})
    assert [name for name, _ in ordered] == ["HT-11", "HT-04"]


def test_worst_first_breaks_a_tie_on_how_much_band_is_left() -> None:
    tight = trend_of([point(date(2022 + n, 1, 1), 14.0, 15.0) for n in range(3)])
    loose = trend_of([point(date(2022 + n, 1, 1), 3.0, 15.0) for n in range(3)])
    ordered = worst_first({"HT-04": loose, "HT-11": tight})
    assert [name for name, _ in ordered] == ["HT-11", "HT-04"]
