from __future__ import annotations

from datetime import date

from quenchline.identity import SensorTag
from quenchline.sensors.calibration import Certificate, Convention
from quenchline.sensors.record import (
    Construction,
    SensorRole,
    SensorStatus,
    Thermocouple,
)
from quenchline.sensors.register import build_register
from quenchline.sensors.reporting import (
    eligibility_table,
    register_summary,
    register_table,
)
from quenchline.sensors.types import ThermocoupleType
from quenchline.sensors.usage import UsageEvent
from quenchline.temperature import Temperature
from quenchline.timespan import hours

TODAY = date(2024, 9, 1)
WORKING = Temperature.fahrenheit(1550)
CERT = Certificate.of(
    "C-24-001",
    date(2024, 3, 1),
    [(600.0, 1.0), (1700.0, 2.0)],
    convention=Convention.CORRECTION,
)


def register() -> object:
    return build_register(
        [
            Thermocouple(
                tag=SensorTag.parse("TC-01"),
                kind=ThermocoupleType.N,
                construction=Construction.NONEXPENDABLE,
                role=SensorRole.SURVEY,
                status=SensorStatus.IN_SERVICE,
                certificate=CERT,
            ),
            Thermocouple(
                tag=SensorTag.parse("TC-02"),
                kind=ThermocoupleType.K,
                construction=Construction.EXPENDABLE,
                role=SensorRole.LOAD,
            ),
        ]
    )


def test_register_table_has_a_row_per_couple() -> None:
    table = register_table(register(), TODAY)  # type: ignore[arg-type]
    rendered = table.render()
    assert "thermocouple register" in rendered
    assert "TC-00001" in rendered
    assert "TC-00002" in rendered
    assert len(table.rows) == 2


def test_register_table_shows_the_calibration_due_date() -> None:
    rendered = register_table(register(), TODAY).render()  # type: ignore[arg-type]
    assert "2025-03-01" in rendered


def test_a_couple_without_a_certificate_shows_a_dash() -> None:
    table = register_table(register(), TODAY)  # type: ignore[arg-type]
    assert table.rows[1][7] is None


def test_register_table_marks_a_spent_couple() -> None:
    reg = register()
    reg.record_use(  # type: ignore[attr-defined]
        "TC-00002",
        UsageEvent(TODAY, Temperature.fahrenheit(1550), hours(2), SensorRole.LOAD),
    )
    table = register_table(reg, TODAY)  # type: ignore[arg-type]
    assert table.rows[1][6] == "spent"


def test_eligibility_table_splits_the_register() -> None:
    table = eligibility_table(register(), SensorRole.SURVEY, WORKING, TODAY)  # type: ignore[arg-type]
    verdicts = [row[1] for row in table.rows]
    assert verdicts == ["eligible", "refused"]
    assert "no calibration certificate" in str(table.rows[1][2])


def test_eligibility_table_titles_itself_with_the_job() -> None:
    table = eligibility_table(register(), SensorRole.LOAD, WORKING, TODAY)  # type: ignore[arg-type]
    assert table.title == "load sensors at 1550 F"


def test_summary_counts_what_matters() -> None:
    summary = register_summary(register(), TODAY)  # type: ignore[arg-type]
    assert "sensor register summary" in summary
    assert "thermocouples   2" in summary
    assert "in service      1" in summary
    assert "no certificate  1" in summary


def test_the_overdue_column_reads_against_the_date_given() -> None:
    early = register_table(register(), date(2024, 9, 1))  # type: ignore[arg-type]
    late = register_table(register(), date(2026, 1, 1))  # type: ignore[arg-type]
    assert early.rows[0][8] == "no"
    assert late.rows[0][8] == "yes"
    assert early.rows[1][8] == "-"
