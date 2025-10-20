from __future__ import annotations

from datetime import date

import pytest

from quenchline.errors import ValidationError
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.temperature import Temperature
from quenchline.timespan import minutes
from quenchline.tus.dropout import (
    DropoutVerdict,
    allowed_losses,
    find_dropouts,
    surviving_keys,
)
from quenchline.tus.survey import Scan, Survey, SurveyPoint, SurveySetpoint


def point(serial: int, corner: bool = False, centre: bool = False) -> SurveyPoint:
    return SurveyPoint(SensorTag.parse(f"TC-{serial}"), f"position {serial}", corner, centre)


def key(serial: int) -> str:
    return f"TC-{serial:05d}"


def scan(elapsed: float, serials: list[int]) -> Scan:
    return Scan.of(minutes(elapsed), {key(s): Temperature.fahrenheit(1550.0) for s in serials})


def build(
    points: tuple[SurveyPoint, ...], scans: tuple[Scan, ...]
) -> tuple[Survey, SurveySetpoint]:
    data = SurveySetpoint(Temperature.fahrenheit(1550), scans)
    survey = Survey(
        "TUS-1", FurnaceTag.parse("HT-04"), "main", date(2024, 9, 3), points, (data,)
    )
    return survey, data


ELEVEN = tuple(
    [point(1, corner=True), point(2, corner=True), point(3, centre=True)]
    + [point(n) for n in range(4, 12)]
)


def test_allowed_losses_rounds_down() -> None:
    assert allowed_losses(9) == 0
    assert allowed_losses(10) == 1
    assert allowed_losses(11) == 1
    assert allowed_losses(25) == 2


def test_allowed_losses_needs_sensors() -> None:
    with pytest.raises(ValidationError):
        allowed_losses(0)


def test_a_clean_survey_loses_nothing() -> None:
    everything = list(range(1, 12))
    survey, data = build(ELEVEN, (scan(0, everything), scan(40, everything)))
    report = find_dropouts(survey, data)
    assert report.survey_stands
    assert report.lost == 0
    assert str(report) == "no sensors lost"


def test_losing_one_padding_sensor_is_acceptable_at_eleven() -> None:
    survey, data = build(ELEVEN, (scan(0, list(range(1, 12))), scan(40, list(range(1, 11)))))
    report = find_dropouts(survey, data)
    assert report.verdict is DropoutVerdict.ACCEPTABLE
    assert report.lost == 1
    assert report.dropouts[0].sensor == key(11)
    assert report.dropouts[0].last_seen == minutes(0)


def test_losing_two_padding_sensors_is_too_many_at_eleven() -> None:
    survey, data = build(ELEVEN, (scan(0, list(range(1, 12))), scan(40, list(range(1, 10)))))
    assert find_dropouts(survey, data).verdict is DropoutVerdict.TOO_MANY_LOST


def test_a_nine_sensor_survey_may_lose_nothing() -> None:
    nine = tuple(
        [point(1, corner=True), point(2, corner=True), point(3, centre=True)]
        + [point(n) for n in range(4, 10)]
    )
    survey, data = build(nine, (scan(0, list(range(1, 10))), scan(40, list(range(1, 9)))))
    assert find_dropouts(survey, data).verdict is DropoutVerdict.TOO_MANY_LOST


def test_losing_a_corner_kills_the_survey_however_few_are_lost() -> None:
    survey, data = build(ELEVEN, (scan(0, list(range(1, 12))), scan(40, list(range(2, 12)))))
    report = find_dropouts(survey, data)
    assert report.verdict is DropoutVerdict.CORNER_LOST
    assert not report.survey_stands
    assert report.dropouts[0].is_critical


def test_losing_the_centre_kills_it_and_takes_priority() -> None:
    remaining = [1, 2, 4, 5, 6, 7, 8, 9, 10, 11]
    survey, data = build(ELEVEN, (scan(0, list(range(1, 12))), scan(40, remaining)))
    assert find_dropouts(survey, data).verdict is DropoutVerdict.CENTRE_LOST


def test_the_centre_verdict_beats_the_corner_one() -> None:
    remaining = [2, 4, 5, 6, 7, 8, 9, 10, 11]
    survey, data = build(ELEVEN, (scan(0, list(range(1, 12))), scan(40, remaining)))
    assert find_dropouts(survey, data).verdict is DropoutVerdict.CENTRE_LOST


def test_a_sensor_that_never_read_is_not_a_dropout() -> None:
    present = list(range(1, 11))
    survey, data = build(ELEVEN, (scan(0, present), scan(40, present)))
    report = find_dropouts(survey, data)
    assert report.lost == 0
    assert report.never_read == (key(11),)
    assert report.survey_stands


def test_a_sensor_that_comes_back_before_the_end_is_not_lost() -> None:
    survey, data = build(
        ELEVEN,
        (
            scan(0, list(range(1, 12))),
            scan(20, list(range(1, 11))),
            scan(40, list(range(1, 12))),
        ),
    )
    assert find_dropouts(survey, data).lost == 0


def test_surviving_keys_drops_both_kinds_of_loss() -> None:
    present = list(range(1, 11))
    survey, data = build(ELEVEN, (scan(0, present), scan(40, list(range(1, 10)))))
    report = find_dropouts(survey, data)
    survivors = surviving_keys(survey, report)
    assert key(11) not in survivors
    assert key(10) not in survivors
    assert len(survivors) == 9


def test_report_text_reports_the_counts() -> None:
    survey, data = build(ELEVEN, (scan(0, list(range(1, 12))), scan(40, list(range(1, 10)))))
    assert "2 lost of an allowed 1" in str(find_dropouts(survey, data))


def test_a_reading_from_a_sensor_the_survey_never_placed_is_ignored() -> None:
    survey, data = build(
        ELEVEN,
        (
            Scan.of(
                minutes(0),
                {
                    **{key(s): Temperature.fahrenheit(1550.0) for s in range(1, 12)},
                    "TC-99999": Temperature.fahrenheit(1550.0),
                },
            ),
            scan(40, list(range(1, 12))),
        ),
    )
    report = find_dropouts(survey, data)
    assert report.lost == 0
    assert report.never_read == ()
