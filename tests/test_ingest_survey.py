from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.identity import SensorTag
from quenchline.ingest.mapping import TimeUnit
from quenchline.ingest.quarantine import RejectReason
from quenchline.ingest.survey import SurveyColumn, SurveyLayout, read_setpoint
from quenchline.temperature import Scale, Temperature
from quenchline.timespan import minutes

SETPOINT = Temperature.fahrenheit(1550)

FILE = """Elapsed (min),Front top left,Front top right,Centre
0,1400,1402,1398
10,1538,1540,1536
40,1548,1552,1550
70,1549,1551,1550
"""


def column(
    heading: str, serial: int, corner: bool = False, centre: bool = False
) -> SurveyColumn:
    return SurveyColumn(
        heading, SensorTag.parse(f"TC-{serial}"), heading.lower(), corner, centre
    )


def layout(**changes: object) -> SurveyLayout:
    base: dict[str, object] = {
        "name": "HT-04 main",
        "time_heading": "Elapsed (min)",
        "time_unit": TimeUnit.MINUTES,
        "scale": Scale.FAHRENHEIT,
        "columns": (
            column("Front top left", 1, corner=True),
            column("Front top right", 2, corner=True),
            column("Centre", 3, centre=True),
        ),
    }
    base.update(changes)
    return SurveyLayout(**base)  # type: ignore[arg-type]


def test_a_column_needs_a_heading() -> None:
    with pytest.raises(ValidationError):
        SurveyColumn("  ", SensorTag.parse("TC-01"), "corner")


def test_layout_validation() -> None:
    with pytest.raises(ValidationError):
        layout(columns=())
    with pytest.raises(ValidationError):
        layout(columns=(column("A", 1), column("B", 1)))
    with pytest.raises(ValidationError):
        layout(columns=(column("A", 1), column(" a ", 2)))


def test_the_layout_reports_its_geometry() -> None:
    built = layout()
    assert built.corner_count == 2
    assert built.keys == ("TC-00001", "TC-00002", "TC-00003")
    assert [p.location for p in built.points] == [
        "front top left",
        "front top right",
        "centre",
    ]
    assert built.points[2].is_centre


def test_dropout_markers_are_stored_lower_cased() -> None:
    built = layout(dropout_markers=("OPEN", " BurnOut "))
    assert built.dropout_markers == ("open", "burnout")
    assert built.read_temperature("OPEN") is None


def test_a_clean_file_reads_into_a_setpoint() -> None:
    result = read_setpoint(FILE, layout(), SETPOINT)
    assert result.succeeded
    data = result.or_raise()
    assert data.setpoint.degf == pytest.approx(1550.0)
    assert len(data.scans) == 4
    assert data.duration == minutes(70)
    assert result.quarantine.is_clean


def test_the_scans_carry_every_position() -> None:
    data = read_setpoint(FILE, layout(), SETPOINT).or_raise()
    assert data.scans[0].keys == ("TC-00001", "TC-00002", "TC-00003")
    assert data.scans[2].get("TC-00002").degf == pytest.approx(1552.0)


def test_a_file_missing_a_position_is_refused() -> None:
    text = "Elapsed (min),Front top left,Centre\n0,1400,1398\n"
    with pytest.raises(ValidationError) as caught:
        read_setpoint(text, layout(), SETPOINT)
    assert "front top right" in str(caught.value)


def test_a_file_with_no_time_column_is_refused() -> None:
    text = "Front top left,Front top right,Centre\n1400,1402,1398\n"
    with pytest.raises(ValidationError):
        read_setpoint(text, layout(), SETPOINT)


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(ValidationError):
        read_setpoint("", layout(), SETPOINT)


def test_a_dropout_leaves_the_scan_standing_with_one_sensor_missing() -> None:
    text = FILE.replace("70,1549,1551,1550", "70,1549,---,1550")
    result = read_setpoint(text, layout(), SETPOINT)
    assert result.quarantine.is_clean
    last = result.or_raise().scans[-1]
    assert last.keys == ("TC-00001", "TC-00003")


def test_a_junk_reading_quarantines_the_row() -> None:
    text = FILE.replace("40,1548,1552,1550", "40,1548,hot,1550")
    result = read_setpoint(text, layout(), SETPOINT)
    assert result.quarantine.by_reason()[RejectReason.BAD_READING] == 1
    assert len(result.or_raise().scans) == 3


def test_a_bad_time_quarantines_the_row() -> None:
    text = FILE.replace("40,1548,1552,1550", "soon,1548,1552,1550")
    result = read_setpoint(text, layout(), SETPOINT)
    assert result.quarantine.by_reason()[RejectReason.BAD_TIME] == 1


def test_a_short_row_quarantines() -> None:
    text = FILE.replace("40,1548,1552,1550", "40,1548")
    result = read_setpoint(text, layout(), SETPOINT)
    assert result.quarantine.by_reason()[RejectReason.SHORT_ROW] == 1


def test_a_blank_row_quarantines() -> None:
    result = read_setpoint(FILE + "\n", layout(), SETPOINT)
    assert result.quarantine.by_reason()[RejectReason.EMPTY] == 1


def test_rows_out_of_order_quarantine() -> None:
    text = (
        "Elapsed (min),Front top left,Front top right,Centre\n"
        "40,1548,1552,1550\n10,1538,1540,1536\n"
    )
    result = read_setpoint(text, layout(), SETPOINT)
    assert result.quarantine.by_reason()[RejectReason.OUT_OF_ORDER] == 1


def test_seconds_and_clock_layouts() -> None:
    seconds = "Elapsed (min),Front top left,Front top right,Centre\n600,1538,1540,1536\n"
    data = read_setpoint(seconds, layout(time_unit=TimeUnit.SECONDS), SETPOINT).or_raise()
    assert data.scans[0].elapsed == minutes(10)

    clock = "Elapsed (min),Front top left,Front top right,Centre\n0:10,1538,1540,1536\n"
    data = read_setpoint(clock, layout(time_unit=TimeUnit.CLOCK), SETPOINT).or_raise()
    assert data.scans[0].elapsed == minutes(10)


def test_a_celsius_layout_converts() -> None:
    text = "Elapsed (min),Front top left,Front top right,Centre\n0,845,846,844\n"
    data = read_setpoint(text, layout(scale=Scale.CELSIUS), SETPOINT).or_raise()
    assert data.scans[0].get("TC-00001").degf == pytest.approx(1553.0)


def test_a_file_with_nothing_usable_produces_nothing() -> None:
    text = "Elapsed (min),Front top left,Front top right,Centre\nsoon,1548,1552,1550\n"
    result = read_setpoint(text, layout(), SETPOINT)
    assert not result.succeeded
    with pytest.raises(ValidationError):
        result.or_raise()


TOML_LAYOUT = """
[layout]
name = "HT-04 main"
time_heading = "Elapsed (min)"
time_unit = "minutes"
scale = "F"
delimiter = ","
dropout_markers = ["", "OPEN"]

  [[layout.column]]
  heading = "Front top left"
  sensor = "TC-01"
  location = "front top left"
  corner = true

  [[layout.column]]
  heading = "Centre"
  sensor = "TC-03"
  centre = true
"""


def test_a_layout_loads_from_toml(tmp_path: object) -> None:
    from pathlib import Path

    from quenchline.ingest.survey import load_layout

    assert isinstance(tmp_path, Path)
    path = tmp_path / "layout.toml"
    path.write_text(TOML_LAYOUT)
    built = load_layout(path)
    assert built.name == "HT-04 main"
    assert built.corner_count == 1
    assert built.keys == ("TC-00001", "TC-00003")
    assert built.dropout_markers == ("", "open")


def test_a_column_without_a_location_uses_its_heading(tmp_path: object) -> None:
    from pathlib import Path

    from quenchline.ingest.survey import load_layout

    assert isinstance(tmp_path, Path)
    path = tmp_path / "layout.toml"
    path.write_text(TOML_LAYOUT)
    built = load_layout(path)
    assert built.columns[1].location == "Centre"


def test_a_missing_layout_file_is_refused(tmp_path: object) -> None:
    from pathlib import Path

    from quenchline.ingest.survey import load_layout

    assert isinstance(tmp_path, Path)
    with pytest.raises(ValidationError):
        load_layout(tmp_path / "nope.toml")


def test_a_layout_missing_a_field_is_refused() -> None:
    from quenchline.ingest.survey import build_layout

    for missing in ("name", "time_heading", "time_unit", "scale"):
        entry = {
            "name": "x",
            "time_heading": "t",
            "time_unit": "minutes",
            "scale": "F",
            "column": [{"heading": "a", "sensor": "TC-01"}],
        }
        del entry[missing]
        with pytest.raises(ValidationError):
            build_layout(entry)


def test_a_layout_with_no_columns_is_refused() -> None:
    from quenchline.ingest.survey import build_layout

    with pytest.raises(ValidationError):
        build_layout({"name": "x", "time_heading": "t", "time_unit": "minutes", "scale": "F"})


def test_a_column_without_a_sensor_is_refused() -> None:
    from quenchline.ingest.survey import build_layout

    with pytest.raises(ValidationError):
        build_layout(
            {
                "name": "x",
                "time_heading": "t",
                "time_unit": "minutes",
                "scale": "F",
                "column": [{"heading": "a"}],
            }
        )


def test_an_unknown_time_unit_is_refused() -> None:
    from quenchline.ingest.survey import build_layout

    with pytest.raises(ValidationError):
        build_layout(
            {
                "name": "x",
                "time_heading": "t",
                "time_unit": "fortnights",
                "scale": "F",
                "column": [{"heading": "a", "sensor": "TC-01"}],
            }
        )
