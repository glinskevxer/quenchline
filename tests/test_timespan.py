from __future__ import annotations

from datetime import timedelta

import pytest

from quenchline.errors import ParseError, ValidationError
from quenchline.timespan import ZERO, Duration, hours, minutes, total


def test_of_adds_the_parts() -> None:
    assert Duration.of(hours=1, minutes=30).seconds == pytest.approx(5400.0)
    assert Duration.of(minutes=90).seconds == pytest.approx(5400.0)
    assert Duration.of(seconds=45).seconds == pytest.approx(45.0)


def test_negative_durations_are_refused() -> None:
    with pytest.raises(ValidationError):
        Duration(-1.0)


def test_parse_clock_notation() -> None:
    assert Duration.parse("1:30") == Duration.of(hours=1, minutes=30)
    assert Duration.parse("0:45:20") == Duration.of(minutes=45, seconds=20)
    assert Duration.parse("12:05") == Duration.of(hours=12, minutes=5)


def test_parse_compound_notation() -> None:
    assert Duration.parse("1h30m") == Duration.of(hours=1, minutes=30)
    assert Duration.parse("90m") == Duration.of(minutes=90)
    assert Duration.parse("45s") == Duration.of(seconds=45)
    assert Duration.parse("2h") == Duration.of(hours=2)
    assert Duration.parse("1 h 30 min") == Duration.of(hours=1, minutes=30)


def test_a_bare_number_is_minutes() -> None:
    assert Duration.parse("90") == Duration.of(minutes=90)
    assert Duration.parse(" 7.5 ") == Duration.of(minutes=7.5)


def test_parse_rejects_junk() -> None:
    for text in ("", "   ", "soon", "1:75"):
        with pytest.raises(ParseError):
            Duration.parse(text)


def test_conversions() -> None:
    d = Duration.of(hours=1, minutes=30)
    assert d.minutes == pytest.approx(90.0)
    assert d.hours == pytest.approx(1.5)
    assert d.as_timedelta() == timedelta(minutes=90)


def test_from_timedelta() -> None:
    assert Duration.from_timedelta(timedelta(minutes=20)).seconds == pytest.approx(1200.0)


def test_arithmetic() -> None:
    assert (minutes(30) + minutes(15)).minutes == pytest.approx(45.0)
    assert (minutes(30) * 2).minutes == pytest.approx(60.0)


def test_subtraction_floors_at_zero() -> None:
    assert (minutes(10) - minutes(30)).seconds == pytest.approx(0.0)


def test_cannot_scale_by_a_negative() -> None:
    with pytest.raises(ValidationError):
        minutes(10) * -1


def test_ordering_and_truthiness() -> None:
    assert minutes(10) < minutes(20)
    assert hours(1) > minutes(59)
    assert bool(minutes(1))
    assert not bool(ZERO)


def test_formatting() -> None:
    assert minutes(90).format() == "1:30"
    assert Duration.of(minutes=45, seconds=20).format() == "0:45:20"
    assert str(hours(2)) == "2:00"


def test_total_sums_a_list() -> None:
    assert total([minutes(10), minutes(20), minutes(5)]).minutes == pytest.approx(35.0)
    assert total([]) == ZERO
