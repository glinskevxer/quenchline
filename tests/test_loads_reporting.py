from __future__ import annotations

from datetime import datetime

from quenchline.identity import FurnaceTag, LotNumber, SensorTag, WorkOrder
from quenchline.loads.deviation import evaluate
from quenchline.loads.disposition import decide
from quenchline.loads.record import Load, PartLine
from quenchline.loads.reporting import (
    channel_table,
    deviation_table,
    load_header,
    parts_table,
    run_summary,
    segment_table,
)
from quenchline.loads.segment import segment
from quenchline.loads.trace import Channel, ChannelRole, Trace
from quenchline.measure import Mass
from quenchline.recipes.cycle import Recipe
from quenchline.recipes.steps import ramp, soak
from quenchline.temperature import Temperature, degf
from quenchline.timespan import minutes

CHARGED = datetime(2024, 11, 12, 6, 30)
STARTED = datetime(2024, 11, 12, 7, 0)
FINISHED = datetime(2024, 11, 12, 12, 0)

HEAT = ramp("heat", Temperature.fahrenheit(1550), maximum_per_hour=800.0)
AUSTENITISE = soak("austenitise", Temperature.fahrenheit(1550), degf(25), minutes(60))
RECIPE = Recipe("HT-4140-Q", "C", "4140 harden", (HEAT, AUSTENITISE))


def trace(readings: list[tuple[float, float | None]]) -> Trace:
    return Trace(
        STARTED,
        (Channel.of("C1", ChannelRole.CONTROL, [(minutes(m), v) for m, v in readings]),),
    )


GOOD = trace([(0.0, 100.0), (30.0, 1545.0), (95.0, 1552.0)])
SHORT = trace([(0.0, 100.0), (30.0, 1545.0), (60.0, 1552.0)])


def load(run: Trace) -> Load:
    return (
        Load(
            lot=LotNumber.parse("L24-0917"),
            work_order=WorkOrder.parse("W104417"),
            furnace=FurnaceTag.parse("HT-04"),
            recipe_code="HT-4140-Q",
            recipe_revision="C",
            parts=(PartLine("PN-8891", 40, "4140", "pinion shaft"),),
            weight=Mass.pounds(1450),
        )
        .charge(CHARGED, (SensorTag.parse("TC-01"),))
        .start(STARTED)
        .attach(run)
        .finish(FINISHED)
    )


def test_load_header_names_everything_on_the_traveller() -> None:
    header = load_header(load(GOOD))
    assert "load record" in header
    assert "lot           L24-0917" in header
    assert "recipe        HT-4140-Q rev C" in header
    assert "pieces        40" in header
    assert "weight        1450.0 lb" in header


def test_parts_table_lists_each_line() -> None:
    table = parts_table(load(GOOD))
    assert len(table.rows) == 1
    assert "pinion shaft" in table.render()


def test_segment_table_shows_what_was_located() -> None:
    segments = segment(RECIPE, GOOD)
    table = segment_table(segments)
    assert len(table.rows) == 2
    assert table.rows[0][2] is None
    assert table.rows[1][4] == "1:05"
    assert table.rows[1][5] == "1:00"


def test_deviation_table_is_empty_on_a_clean_run() -> None:
    findings = evaluate(segment(RECIPE, GOOD), GOOD)
    assert deviation_table(findings).is_empty


def test_deviation_table_lists_the_findings() -> None:
    findings = evaluate(segment(RECIPE, SHORT), SHORT)
    table = deviation_table(findings)
    assert len(table.rows) == 1
    assert "short_soak" in table.render()


def test_channel_table_counts_samples_and_gaps() -> None:
    run = trace([(0.0, 100.0), (30.0, None), (60.0, 1545.0), (95.0, 1552.0)])
    table = channel_table(run)
    assert table.rows[0][2] == 4
    assert table.rows[0][3] == 3
    assert table.rows[0][5] == 1
    assert table.rows[0][6] == 1


def test_run_summary_on_a_clean_run() -> None:
    findings = evaluate(segment(RECIPE, GOOD), GOOD)
    summary = run_summary(load(GOOD), findings, decide(findings))
    assert "run summary" in summary
    assert "deviations   0" in summary
    assert "disposition  accept" in summary
    assert "ships        yes" in summary
    assert "worst        -" in summary


def test_run_summary_on_a_short_run() -> None:
    findings = evaluate(segment(RECIPE, SHORT), SHORT)
    summary = run_summary(load(SHORT), findings, decide(findings))
    assert "critical     1" in summary
    assert "ships        no" in summary
