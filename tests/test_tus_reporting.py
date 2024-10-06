from __future__ import annotations

from datetime import date

from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.temperature import Temperature
from quenchline.timespan import minutes
from quenchline.tus.dropout import find_dropouts
from quenchline.tus.evaluate import evaluate
from quenchline.tus.history import SurveyHistory, SurveyOutcome
from quenchline.tus.reporting import (
    dropout_note,
    due_board,
    excursion_table,
    setpoint_table,
    survey_header,
)
from quenchline.tus.survey import Scan, Survey, SurveyPoint, SurveySetpoint

TODAY = date(2024, 10, 1)


def scan(elapsed: float, values: dict[str, float]) -> Scan:
    return Scan.of(minutes(elapsed), {k: Temperature.fahrenheit(v) for k, v in values.items()})


def build(*scans: Scan, setpoint: float = 1550.0) -> Survey:
    data = SurveySetpoint(Temperature.fahrenheit(setpoint), scans)
    return Survey(
        "TUS-2410-04",
        FurnaceTag.parse("HT-04"),
        "main",
        date(2024, 9, 3),
        (
            SurveyPoint(SensorTag.parse("TC-01"), "front left", is_corner=True),
            SurveyPoint(SensorTag.parse("TC-02"), "centre", is_centre=True),
        ),
        (data,),
    )


GOOD = build(
    scan(0, {"TC-00001": 1540.0, "TC-00002": 1541.0}),
    scan(40, {"TC-00001": 1552.0, "TC-00002": 1548.0}),
)
BAD = build(
    scan(0, {"TC-00001": 1540.0, "TC-00002": 1541.0}),
    scan(40, {"TC-00001": 1590.0, "TC-00002": 1520.0}),
)


def test_setpoint_table_lists_each_setpoint() -> None:
    table = setpoint_table(evaluate(GOOD, FurnaceClass.CLASS_3))
    assert len(table.rows) == 1
    rendered = table.render()
    assert "uniformity survey TUS-2410-04" in rendered
    assert "passed" in rendered


def test_setpoint_table_names_the_failure_reasons() -> None:
    table = setpoint_table(evaluate(BAD, FurnaceClass.CLASS_3))
    assert "overshoot" in str(table.rows[0][7])


def test_excursion_table_is_empty_for_a_clean_survey() -> None:
    table = excursion_table(evaluate(GOOD, FurnaceClass.CLASS_3))
    assert table.is_empty
    assert "(no rows)" in table.render()


def test_excursion_table_lists_every_bad_reading() -> None:
    table = excursion_table(evaluate(BAD, FurnaceClass.CLASS_3))
    sensors = {row[2] for row in table.rows}
    assert sensors == {"TC-00001", "TC-00002"}


def test_survey_header_describes_the_geometry() -> None:
    header = survey_header(evaluate(GOOD, FurnaceClass.CLASS_3))
    assert "uniformity survey" in header
    assert "sensors       2" in header
    assert "corners       1" in header
    assert "centre point  yes" in header
    assert "verdict       passed" in header


def test_dropout_note_says_nothing_when_nothing_was_lost() -> None:
    report = find_dropouts(GOOD, GOOD.setpoints[0])
    assert dropout_note(report) == "no sensors lost"


def test_dropout_note_reports_a_loss() -> None:
    lost = build(
        scan(0, {"TC-00001": 1540.0, "TC-00002": 1541.0}),
        scan(40, {"TC-00002": 1548.0}),
    )
    report = find_dropouts(lost, lost.setpoints[0])
    note = dropout_note(report)
    assert "survey sensor losses" in note
    assert "survey stands  no" in note


def test_due_board_orders_by_urgency() -> None:
    early = SurveyHistory(
        FurnaceTag.parse("HT-04"), "main", FurnaceClass.CLASS_3, InstrumentationType.C
    )
    early.file(SurveyOutcome("TUS-1", date(2023, 1, 1), True, (Temperature.fahrenheit(1550),)))
    late = SurveyHistory(
        FurnaceTag.parse("HT-05"), "main", FurnaceClass.CLASS_3, InstrumentationType.C
    )
    late.file(SurveyOutcome("TUS-2", date(2024, 9, 1), True, (Temperature.fahrenheit(1550),)))
    never = SurveyHistory(
        FurnaceTag.parse("HT-06"), "main", FurnaceClass.CLASS_3, InstrumentationType.C
    )
    board = due_board([late, early, never], TODAY)
    assert [row[0] for row in board.rows] == ["HT-06", "HT-04", "HT-05"]
    assert board.rows[0][7] == "never surveyed"
    assert board.rows[1][7] == "overdue"
    assert board.rows[2][7] == "in date"


def test_due_board_shows_the_qualified_range() -> None:
    history = SurveyHistory(
        FurnaceTag.parse("HT-04"), "main", FurnaceClass.CLASS_3, InstrumentationType.C
    )
    history.file(
        SurveyOutcome(
            "TUS-1",
            date(2024, 9, 1),
            True,
            (Temperature.fahrenheit(1200), Temperature.fahrenheit(1700)),
        )
    )
    board = due_board([history], TODAY)
    assert board.rows[0][6] == "1200 F to 1700 F"


def test_due_board_shows_a_dash_for_an_unqualified_zone() -> None:
    never = SurveyHistory(
        FurnaceTag.parse("HT-06"), "main", FurnaceClass.CLASS_3, InstrumentationType.C
    )
    board = due_board([never], TODAY)
    assert board.rows[0][6] is None
