from __future__ import annotations

from datetime import date, datetime

import pytest

from quenchline.errors import ValidationError
from quenchline.identity import FurnaceTag, LotNumber, WorkOrder
from quenchline.loads.disposition import Disposition
from quenchline.loads.record import Load, LoadState, PartLine
from quenchline.report.kpi import Period, comparison_table, rollup, rollup_block

PERIOD = Period(date(2025, 1, 1), date(2025, 3, 31))


def load(
    lot: str,
    state: LoadState = LoadState.CERTIFIED,
    finished: datetime | None = datetime(2025, 2, 4, 12),
    pieces: int = 10,
) -> Load:
    return Load(
        lot=LotNumber.parse(lot),
        work_order=WorkOrder.parse("W104417"),
        furnace=FurnaceTag.parse("HT-04"),
        recipe_code="HT-4140-Q",
        recipe_revision="C",
        parts=(PartLine("PN-8891", pieces),),
        state=state,
        finished_at=finished,
    )


def test_period_validation_and_length() -> None:
    assert PERIOD.days == 90
    assert PERIOD.contains(date(2025, 2, 4))
    assert not PERIOD.contains(date(2025, 4, 1))
    assert str(PERIOD) == "2025-01-01 to 2025-03-31"
    with pytest.raises(ValidationError):
        Period(date(2025, 3, 31), date(2025, 1, 1))


def test_a_single_day_period() -> None:
    assert Period(date(2025, 1, 1), date(2025, 1, 1)).days == 1


def test_loads_outside_the_period_are_ignored() -> None:
    result = rollup(
        [load("L25-0001"), load("L25-0002", finished=datetime(2024, 12, 1, 12))],
        PERIOD,
    )
    assert result.loads == 1


def test_unfinished_loads_are_ignored() -> None:
    result = rollup([load("L25-0001", LoadState.RUNNING, None)], PERIOD)
    assert result.loads == 0
    assert result.first_pass_yield is None


def test_pieces_are_summed() -> None:
    result = rollup([load("L25-0001", pieces=10), load("L25-0002", pieces=32)], PERIOD)
    assert result.pieces == 42


def test_first_pass_yield_ignores_concessions() -> None:
    loads = [load("L25-0001"), load("L25-0002"), load("L25-0003")]
    dispositions = {"L25-0002": Disposition.ACCEPT_AS_IS}
    result = rollup(loads, PERIOD, dispositions=dispositions)
    assert result.certified == 3
    assert result.concessions == 1
    assert result.certified_share == pytest.approx(1.0)
    assert result.first_pass_yield == pytest.approx(2 / 3)


def test_rejected_loads_pull_both_numbers_down() -> None:
    loads = [load("L25-0001"), load("L25-0002", LoadState.REJECTED)]
    result = rollup(loads, PERIOD)
    assert result.finished == 2
    assert result.certified_share == pytest.approx(0.5)
    assert result.first_pass_yield == pytest.approx(0.5)


def test_yield_never_goes_negative() -> None:
    loads = [load("L25-0001")]
    dispositions = {"L25-0001": Disposition.ACCEPT_AS_IS}
    result = rollup(loads, PERIOD, dispositions=dispositions)
    assert result.first_pass_yield == pytest.approx(0.0)


def test_deviation_rate_is_per_finished_load() -> None:
    loads = [load("L25-0001"), load("L25-0002")]
    result = rollup(loads, PERIOD, deviations={"L25-0001": 3, "L25-0002": 1})
    assert result.deviations == 4
    assert result.deviation_rate == pytest.approx(2.0)


def test_utilisation_needs_a_furnace_count() -> None:
    loads = [load("L25-0001"), load("L25-0002")]
    assert rollup(loads, PERIOD).loads_per_furnace is None
    assert rollup(loads, PERIOD, furnace_count=4).loads_per_furnace == pytest.approx(0.5)


def test_loads_per_day_uses_the_period_length() -> None:
    result = rollup([load("L25-0001")], PERIOD)
    assert result.loads_per_day == pytest.approx(1 / 90)


def test_an_empty_period_reports_dashes() -> None:
    block = rollup_block(rollup([], PERIOD))
    assert "first pass yield     -" in block
    assert "loads                0" in block


def test_the_block_reports_the_percentages() -> None:
    loads = [load("L25-0001"), load("L25-0002", LoadState.REJECTED)]
    block = rollup_block(rollup(loads, PERIOD))
    assert "shop performance" in block
    assert "50.0 percent" in block


def test_the_comparison_table_names_the_direction() -> None:
    previous = rollup([load("L25-0001")], PERIOD)
    current = rollup([load("L25-0002"), load("L25-0003")], PERIOD)
    table = comparison_table(current, previous)
    assert table.rows[0][3] == "up"
    assert len(table.rows) == 4


def test_a_flat_measure_says_flat() -> None:
    previous = rollup([load("L25-0001")], PERIOD)
    current = rollup([load("L25-0002")], PERIOD)
    table = comparison_table(current, previous)
    assert table.rows[0][3] == "flat"


def test_a_falling_measure_says_down() -> None:
    previous = rollup([load("L25-0001"), load("L25-0002")], PERIOD)
    current = rollup([load("L25-0003")], PERIOD)
    assert comparison_table(current, previous).rows[0][3] == "down"


def test_an_unknown_measure_shows_a_dash() -> None:
    previous = rollup([], PERIOD)
    current = rollup([load("L25-0001")], PERIOD)
    table = comparison_table(current, previous)
    assert table.rows[2][3] == "-"
    assert table.rows[2][1] == "-"
