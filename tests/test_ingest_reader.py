from __future__ import annotations

from datetime import datetime

import pytest

from quenchline.errors import ValidationError
from quenchline.ingest.mapping import ColumnMap, MappingProfile, TimeUnit
from quenchline.ingest.quarantine import RejectReason
from quenchline.ingest.reader import elapsed_span, read_text
from quenchline.loads.trace import ChannelRole
from quenchline.temperature import Scale
from quenchline.timespan import minutes

STARTED = datetime(2025, 2, 5, 6, 30)

PROFILE = MappingProfile(
    name="eurotherm 6100",
    time_heading="Elapsed (min)",
    time_unit=TimeUnit.MINUTES,
    scale=Scale.FAHRENHEIT,
    columns=(
        ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),
        ColumnMap("Channel 2", "L1", ChannelRole.LOAD),
    ),
)

GOOD = """Elapsed (min),Channel 1,Channel 2,Ambient
0,100,95,70
30,1545,1538,72
60,1552,1549,72
"""


def test_a_clean_file_reads_into_a_trace() -> None:
    result = read_text(GOOD, PROFILE, STARTED, source="run.csv")
    assert result.succeeded
    trace = result.trace_or_raise()
    assert trace.keys == ("C1", "L1")
    assert trace.source == "run.csv"
    assert result.quarantine.is_clean
    assert result.rows == 3


def test_the_time_column_becomes_elapsed_duration() -> None:
    trace = read_text(GOOD, PROFILE, STARTED).trace_or_raise()
    assert trace.channel("C1").end == minutes(60)
    assert elapsed_span(read_text(GOOD, PROFILE, STARTED)) == minutes(60)


def test_unmapped_columns_are_ignored() -> None:
    trace = read_text(GOOD, PROFILE, STARTED).trace_or_raise()
    assert "Ambient" not in trace.keys


def test_readings_come_back_on_the_profile_scale() -> None:
    celsius = MappingProfile(
        name="c",
        time_heading="Elapsed (min)",
        time_unit=TimeUnit.MINUTES,
        scale=Scale.CELSIUS,
        columns=(ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),),
    )
    text = "Elapsed (min),Channel 1\n0,100\n30,845\n"
    trace = read_text(text, celsius, STARTED).trace_or_raise()
    peak = trace.channel("C1").peak()
    assert peak is not None
    assert peak.degf == pytest.approx(1553.0)


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(ValidationError):
        read_text("", PROFILE, STARTED)


def test_a_file_missing_a_mapped_column_is_refused() -> None:
    with pytest.raises(ValidationError):
        read_text("Elapsed (min),Channel 1\n0,100\n", PROFILE, STARTED)


def test_a_file_with_no_time_column_is_refused() -> None:
    with pytest.raises(ValidationError):
        read_text("Channel 1,Channel 2\n100,95\n", PROFILE, STARTED)


def test_a_blank_row_is_quarantined() -> None:
    text = GOOD + "\n"
    result = read_text(text, PROFILE, STARTED)
    assert result.quarantine.by_reason()[RejectReason.EMPTY] == 1
    assert result.succeeded


def test_a_short_row_is_quarantined() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\n0,100,95\n30,1545\n60,1552,1549\n"
    result = read_text(text, PROFILE, STARTED)
    assert result.quarantine.by_reason()[RejectReason.SHORT_ROW] == 1
    assert result.trace_or_raise().channel("C1").samples[1].elapsed == minutes(60)


def test_a_bad_time_is_quarantined() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\n0,100,95\nsoon,1545,1538\n"
    result = read_text(text, PROFILE, STARTED)
    assert result.quarantine.by_reason()[RejectReason.BAD_TIME] == 1


def test_a_bad_reading_is_quarantined() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\n0,100,95\n30,hot,1538\n"
    result = read_text(text, PROFILE, STARTED)
    assert result.quarantine.by_reason()[RejectReason.BAD_READING] == 1


def test_a_bad_reading_takes_the_whole_row_not_one_channel() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\n0,100,95\n30,hot,1538\n60,1552,1549\n"
    trace = read_text(text, PROFILE, STARTED).trace_or_raise()
    assert len(trace.channel("C1").samples) == 2
    assert len(trace.channel("L1").samples) == 2


def test_a_dropout_marker_is_kept_as_a_dropout_rather_than_quarantined() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\n0,100,95\n30,---,1538\n60,1552,1549\n"
    result = read_text(text, PROFILE, STARTED)
    assert result.quarantine.is_clean
    channel = result.trace_or_raise().channel("C1")
    assert len(channel.samples) == 3
    assert not channel.samples[1].is_reading


def test_a_repeated_timestamp_is_quarantined_rather_than_overwritten() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\n0,100,95\n30,1545,1538\n30,1546,1539\n"
    result = read_text(text, PROFILE, STARTED)
    assert result.quarantine.by_reason()[RejectReason.DUPLICATE_TIME] == 1
    channel = result.trace_or_raise().channel("C1")
    assert len(channel.samples) == 2


def test_a_row_out_of_order_is_quarantined() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\n0,100,95\n60,1552,1549\n30,1545,1538\n"
    result = read_text(text, PROFILE, STARTED)
    assert result.quarantine.by_reason()[RejectReason.OUT_OF_ORDER] == 1


def test_a_file_with_no_usable_rows_produces_no_trace() -> None:
    text = "Elapsed (min),Channel 1,Channel 2\nsoon,1545,1538\n"
    result = read_text(text, PROFILE, STARTED)
    assert not result.succeeded
    with pytest.raises(ValidationError):
        result.trace_or_raise()
    assert elapsed_span(result).seconds == pytest.approx(0.0)


def test_the_digest_ignores_line_endings() -> None:
    unix = read_text(GOOD, PROFILE, STARTED)
    windows = read_text(GOOD.replace("\n", "\r\n"), PROFILE, STARTED)
    assert unix.digest == windows.digest


def test_a_tab_delimited_profile_reads_tabs() -> None:
    tabbed = MappingProfile(
        name="tabbed",
        time_heading="Elapsed (min)",
        time_unit=TimeUnit.MINUTES,
        scale=Scale.FAHRENHEIT,
        columns=(ColumnMap("Channel 1", "C1", ChannelRole.CONTROL),),
        delimiter="\t",
    )
    text = "Elapsed (min)\tChannel 1\n0\t100\n30\t1545\n"
    assert read_text(text, tabbed, STARTED).succeeded
