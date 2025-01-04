from __future__ import annotations

from datetime import date

from quenchline.calendar_rules import Interval
from quenchline.furnaces.classes import FurnaceClass, InstrumentationType
from quenchline.identity import FurnaceTag, InstrumentTag, SensorTag
from quenchline.instruments.calibration import CalibrationCheck, InstrumentCalibration
from quenchline.instruments.record import Instrument
from quenchline.instruments.register import build_register as build_instruments
from quenchline.instruments.types import (
    Accuracy,
    InstrumentClass,
    InstrumentFunction,
    Span,
)
from quenchline.quench.bath import Bath
from quenchline.quench.media import Agitation, oil
from quenchline.sat.model import SatReading, SatTest
from quenchline.sat.schedule import SatHistory
from quenchline.schedule.board import Board, board_summary, board_table
from quenchline.schedule.policy import Activity, Urgency
from quenchline.sensors.calibration import Certificate, Convention
from quenchline.sensors.record import Construction, SensorRole, Thermocouple
from quenchline.sensors.register import build_register as build_sensors
from quenchline.sensors.types import ThermocoupleType
from quenchline.temperature import Scale, Temperature, TemperatureDelta, degf
from quenchline.tus.history import SurveyHistory, SurveyOutcome

TODAY = date(2025, 2, 3)
ZERO = TemperatureDelta(0.0, Scale.FAHRENHEIT)
SPAN = Span(Temperature.fahrenheit(0), Temperature.fahrenheit(2400))


def instruments() -> object:
    register = build_instruments(
        [
            Instrument(
                tag=InstrumentTag.parse("IC-04"),
                function=InstrumentFunction.CONTROLLING,
                span=SPAN,
                accuracy=Accuracy(0.1, InstrumentClass.PERCENT_OF_READING),
                resolution=TemperatureDelta(1.0, Scale.FAHRENHEIT),
                interval=Interval.months(6),
            )
        ]
    )
    register.file_calibration(
        InstrumentCalibration(
            "CAL-1",
            InstrumentTag.parse("IC-04"),
            date(2024, 6, 10),
            (CalibrationCheck(Temperature.fahrenheit(1550), Temperature.fahrenheit(1550.5)),),
            TemperatureDelta(2.0, Scale.FAHRENHEIT),
        )
    )
    return register


def sensors() -> object:
    return build_sensors(
        [
            Thermocouple(
                tag=SensorTag.parse("TC-01"),
                kind=ThermocoupleType.N,
                construction=Construction.NONEXPENDABLE,
                role=SensorRole.SURVEY,
                certificate=Certificate.of(
                    "C-1",
                    date(2024, 12, 1),
                    [(600.0, 1.0), (1700.0, 2.0)],
                    convention=Convention.CORRECTION,
                ),
            )
        ]
    )


def sat_histories() -> list[SatHistory]:
    history = SatHistory(FurnaceTag.parse("HT-04"), FurnaceClass.CLASS_3, InstrumentationType.D)
    history.file(
        SatTest(
            "SAT-1",
            FurnaceTag.parse("HT-04"),
            date(2024, 11, 1),
            Temperature.fahrenheit(1550),
            SatReading(Temperature.fahrenheit(1550), ZERO, ZERO, SensorTag.parse("TC-01")),
            SatReading(Temperature.fahrenheit(1550), ZERO, ZERO, SensorTag.parse("TC-99")),
        )
    )
    return [history]


def survey_histories() -> list[SurveyHistory]:
    history = SurveyHistory(
        FurnaceTag.parse("HT-04"), "main", FurnaceClass.CLASS_3, InstrumentationType.D
    )
    history.file(
        SurveyOutcome("TUS-1", date(2024, 12, 1), True, (Temperature.fahrenheit(1550),))
    )
    return [history]


def baths() -> list[Bath]:
    return [
        Bath(
            "QT-1",
            oil("AAA fast oil", Temperature.fahrenheit(130), degf(20)),
            2000.0,
            Temperature.fahrenheit(130),
            Agitation.GOOD,
            last_checked=date(2025, 2, 1),
        )
    ]


def board() -> Board:
    return Board.build(
        TODAY,
        instruments=instruments(),  # type: ignore[arg-type]
        sensors=sensors(),  # type: ignore[arg-type]
        sat=sat_histories(),
        surveys=survey_histories(),
        baths=baths(),
    )


def test_the_board_gathers_every_register() -> None:
    b = board()
    assert len(b) == 5
    assert {item.activity for item in b.items} == set(Activity)


def test_an_empty_board_is_allowed() -> None:
    assert len(Board.build(TODAY)) == 0


def test_the_board_is_ranked_worst_first() -> None:
    b = board()
    assert b.items[0].urgency.rank <= b.items[-1].urgency.rank


def test_the_overdue_instrument_needs_attention() -> None:
    items = [i for i in board().items if i.activity is Activity.INSTRUMENT_CALIBRATION]
    assert items[0].urgency is Urgency.OVERDUE
    assert items[0].detail == "controlling"


def test_a_healthy_bath_check_does_not_need_attention() -> None:
    items = board().of(Activity.BATH_CHECK)
    assert items[0].urgency is Urgency.DUE_SOON
    assert not items[0].needs_attention


def test_blocking_furnaces_only_lists_what_stops_a_furnace() -> None:
    blocking = board().blocking_furnaces()
    assert all(i.activity.stops_the_furnace for i in blocking)


def test_grace_softens_overdue_to_due_now_without_hiding_it() -> None:
    strict = Board.build(TODAY, instruments=instruments())  # type: ignore[arg-type]
    lenient = Board.build(TODAY, instruments=instruments(), grace=120)  # type: ignore[arg-type]
    assert strict.items[0].urgency is Urgency.OVERDUE
    assert lenient.items[0].urgency is Urgency.DUE_NOW
    assert lenient.needing_attention()


def test_a_sensor_with_no_certificate_is_never_done() -> None:
    register = build_sensors(
        [
            Thermocouple(
                tag=SensorTag.parse("TC-02"),
                kind=ThermocoupleType.N,
                construction=Construction.NONEXPENDABLE,
                role=SensorRole.SURVEY,
            )
        ]
    )
    b = Board.build(TODAY, sensors=register)
    assert b.items[0].urgency is Urgency.NEVER_DONE


def test_board_table_renders_every_row() -> None:
    table = board_table(board(), TODAY)
    assert len(table.rows) == 5
    assert "shop schedule as of 2025-02-03" in table.render()


def test_board_summary_counts_the_problems() -> None:
    summary = board_summary(board(), TODAY)
    assert "schedule summary" in summary
    assert "items              5" in summary
    assert "needing attention" in summary


def test_board_summary_of_nothing_says_so() -> None:
    summary = board_summary(Board.build(TODAY), TODAY)
    assert "worst              -" in summary
