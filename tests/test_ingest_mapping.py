from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.ingest.mapping import (
    ColumnMap,
    MappingProfile,
    TimeUnit,
    normalise_heading,
)
from quenchline.loads.trace import ChannelRole
from quenchline.temperature import Scale
from quenchline.timespan import minutes


def profile(**changes: object) -> MappingProfile:
    base: dict[str, object] = {
        "name": "eurotherm 6100",
        "time_heading": "Elapsed (min)",
        "time_unit": TimeUnit.MINUTES,
        "scale": Scale.FAHRENHEIT,
        "columns": (
            ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),
            ColumnMap("Channel 2", "L1", ChannelRole.LOAD),
        ),
    }
    base.update(changes)
    return MappingProfile(**base)  # type: ignore[arg-type]


def test_heading_normalisation() -> None:
    assert normalise_heading("  Channel   1 ") == "channel 1"
    assert normalise_heading("TC1") == "tc1"


def test_time_units_know_whether_they_are_elapsed() -> None:
    assert TimeUnit.SECONDS.is_elapsed
    assert TimeUnit.HOURS.is_elapsed
    assert not TimeUnit.CLOCK.is_elapsed


def test_column_validation() -> None:
    with pytest.raises(ValidationError):
        ColumnMap("  ", "C1", ChannelRole.CONTROL)
    with pytest.raises(ValidationError):
        ColumnMap("Channel 1", " ", ChannelRole.CONTROL)


def test_profile_validation() -> None:
    with pytest.raises(ValidationError):
        profile(name="  ")
    with pytest.raises(ValidationError):
        profile(time_heading="")
    with pytest.raises(ValidationError):
        profile(columns=())


def test_two_columns_cannot_share_a_key() -> None:
    with pytest.raises(ValidationError):
        profile(
            columns=(
                ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),
                ColumnMap("Channel 2", "C1", ChannelRole.LOAD),
            )
        )


def test_two_columns_cannot_match_the_same_heading() -> None:
    with pytest.raises(ValidationError):
        profile(
            columns=(
                ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),
                ColumnMap(" channel  1 ", "L1", ChannelRole.LOAD),
            )
        )


def test_headings_match_regardless_of_case_and_spacing() -> None:
    p = profile()
    column = p.column_for("  CHANNEL   1 ")
    assert column is not None
    assert column.key == "C1"


def test_matching_is_not_fuzzy() -> None:
    assert profile().column_for("Channel 11") is None


def test_resolve_finds_every_mapped_column() -> None:
    headings = ["Elapsed (min)", "Channel 1", "Ambient", "Channel 2"]
    resolved = profile().resolve(headings)
    assert {index: column.key for index, column in resolved.items()} == {1: "C1", 3: "L1"}


def test_resolve_refuses_a_file_missing_a_mapped_column() -> None:
    with pytest.raises(ValidationError) as caught:
        profile().resolve(["Elapsed (min)", "Channel 1"])
    assert "L1" in str(caught.value)


def test_resolve_refuses_a_duplicated_heading() -> None:
    with pytest.raises(ValidationError):
        profile().resolve(["Elapsed (min)", "Channel 1", "channel 1", "Channel 2"])


def test_time_index_is_found_by_heading() -> None:
    assert profile().time_index(["Elapsed (min)", "Channel 1"]) == 0
    assert profile().time_index(["Channel 1", " elapsed (MIN) "]) == 1


def test_a_file_with_no_time_column_is_refused() -> None:
    with pytest.raises(ValidationError):
        profile().time_index(["Channel 1", "Channel 2"])


def test_elapsed_time_is_read_in_the_stated_unit() -> None:
    assert profile().read_time("90") == minutes(90)
    assert profile(time_unit=TimeUnit.SECONDS).read_time("90").seconds == pytest.approx(90.0)
    assert profile(time_unit=TimeUnit.HOURS).read_time("1.5") == minutes(90)


def test_clock_times_are_parsed() -> None:
    assert profile(time_unit=TimeUnit.CLOCK).read_time("1:30") == minutes(90)


def test_bad_time_cells_are_refused() -> None:
    p = profile()
    with pytest.raises(ValidationError):
        p.read_time("  ")
    with pytest.raises(ValidationError):
        p.read_time("soon")
    with pytest.raises(ValidationError):
        p.read_time("-5")


def test_temperatures_are_read_on_the_profile_scale() -> None:
    assert profile().read_temperature("1550").degf == pytest.approx(1550.0)  # type: ignore[union-attr]
    celsius = profile(scale=Scale.CELSIUS).read_temperature("845")
    assert celsius is not None
    assert celsius.degf == pytest.approx(1553.0)


def test_dropout_markers_read_as_nothing() -> None:
    p = profile()
    for marker in ("", "  ", "---", "N/A", "OPEN", "burnout", "####"):
        assert p.read_temperature(marker) is None
        assert p.is_dropout(marker)


def test_the_dropout_markers_can_be_replaced() -> None:
    p = profile(dropout_markers=("xxx",))
    assert p.read_temperature("xxx") is None
    with pytest.raises(ValidationError):
        p.read_temperature("---")


def test_a_junk_reading_is_refused() -> None:
    with pytest.raises(ValidationError):
        profile().read_temperature("hot")


def test_the_profile_reports_its_keys() -> None:
    assert profile().keys == ("C1", "L1")
