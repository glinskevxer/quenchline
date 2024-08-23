from __future__ import annotations

from datetime import date

from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag, SensorTag
from quenchline.sat.model import SatReading, SatTest
from quenchline.sat.reporting import (
    due_board,
    failure_notice,
    history_summary,
    result_table,
)
from quenchline.sat.schedule import SatHistory
from quenchline.temperature import Scale, Temperature, TemperatureDelta

SETPOINT = Temperature.fahrenheit(1550)
ZERO = TemperatureDelta(0.0, Scale.FAHRENHEIT)
TODAY = date(2024, 8, 20)


def side(indicated: float, tag: str) -> SatReading:
    return SatReading(Temperature.fahrenheit(indicated), ZERO, ZERO, SensorTag.parse(tag))


def sat(number: str, performed: date, system: float, furnace: FurnaceTag) -> SatTest:
    return SatTest(
        number, furnace, performed, SETPOINT, side(system, "TC-01"), side(1550.0, "TC-99")
    )


def history(tag: str = "HT-04") -> SatHistory:
    return SatHistory(FurnaceTag.parse(tag), FurnaceClass.CLASS_3, InstrumentationType.D)


def test_result_table_lists_every_test() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0, h.furnace))
    h.file(sat("SAT-2", date(2024, 8, 1), 1570.0, h.furnace))
    table = result_table(h)
    assert len(table.rows) == 2
    rendered = table.render()
    assert "system accuracy tests on HT-04" in rendered
    assert "passed" in rendered
    assert "failed" in rendered


def test_result_table_of_an_empty_history() -> None:
    assert "(no rows)" in result_table(history()).render()


def test_due_board_puts_the_worst_first() -> None:
    early = history("HT-04")
    early.file(sat("SAT-1", date(2024, 1, 1), 1550.0, early.furnace))
    late = history("HT-05")
    late.file(sat("SAT-2", date(2024, 8, 15), 1550.0, late.furnace))
    never = history("HT-06")
    board = due_board([late, early, never], TODAY)
    assert [row[0] for row in board.rows] == ["HT-06", "HT-04", "HT-05"]
    assert board.rows[0][5] == "never tested"
    assert board.rows[1][5] == "overdue"
    assert board.rows[2][5] == "in date"


def test_due_board_honours_grace() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 7, 1), 1550.0, h.furnace))
    strict = due_board([h], TODAY)
    lenient = due_board([h], TODAY, grace=60)
    assert strict.rows[0][5] == "overdue"
    assert lenient.rows[0][5] == "in date"


def test_failure_notice_names_the_window() -> None:
    h = history()
    h.file(sat("SAT-1", date(2024, 5, 1), 1550.0, h.furnace))
    bad = h.file(sat("SAT-2", date(2024, 7, 1), 1580.0, h.furnace))
    notice = failure_notice(h, bad)
    assert "system accuracy test failure" in notice
    assert "work in doubt from  2024-05-01" in notice
    assert "work in doubt to    2024-07-01" in notice


def test_failure_notice_on_a_pass_says_nothing_to_report() -> None:
    h = history()
    good = h.file(sat("SAT-1", date(2024, 5, 1), 1550.0, h.furnace))
    assert "nothing to report" in failure_notice(h, good)


def test_history_summary_reports_the_run() -> None:
    h = history()
    for index in range(2):
        h.file(sat(f"SAT-{index}", date(2024, 6 + index, 1), 1550.0, h.furnace))
    summary = history_summary(h, TODAY)
    assert "sat summary" in summary
    assert "consecutive passes  2" in summary
    assert "instrumentation     D" in summary


def test_history_summary_of_an_untested_furnace() -> None:
    summary = history_summary(history(), TODAY)
    assert "next due            -" in summary
    assert "latest verdict      -" in summary
