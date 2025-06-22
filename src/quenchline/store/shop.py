"""One handle on the whole store, and the questions that cross tables.

The repositories are deliberately narrow: each one knows one aggregate and
nothing else. That is right for writing and wrong for the three or four
questions the shop actually asks, all of which cross tables:

* what has this furnace run, and is any of it in doubt;
* which loads fall inside the suspect window of an open equipment report;
* what is on the floor right now.

Those live here rather than being pushed into one repository or the other,
because putting "which loads does this instrument throw into doubt" on the load
repository makes the load repository know about instruments, and putting it on
the instrument repository makes the instrument repository know about loads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path

from ..identity import FurnaceTag
from ..loads.record import Load, LoadState
from ..nonconformance.record import Nonconformance
from .database import Database
from .furnaces import FurnaceRepository
from .loads import LoadRepository
from .nonconformance import NcrRepository
from .recipes import RecipeRepository
from .sat import SatRepository
from .sensors import SensorRepository


@dataclass
class Shop:
    """Every repository over one database."""

    database: Database
    furnaces: FurnaceRepository
    sensors: SensorRepository
    loads: LoadRepository
    reports: NcrRepository
    sat: SatRepository
    recipes: RecipeRepository

    @classmethod
    def open(cls, path: Path | str) -> Shop:
        database = Database.open(path)
        return cls.over(database)

    @classmethod
    def in_memory(cls) -> Shop:
        return cls.over(Database.in_memory())

    @classmethod
    def over(cls, database: Database) -> Shop:
        return cls(
            database,
            FurnaceRepository(database),
            SensorRepository(database),
            LoadRepository(database),
            NcrRepository(database),
            SatRepository(database),
            RecipeRepository(database),
        )

    def close(self) -> None:
        self.database.close()

    def __enter__(self) -> Shop:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def on_the_floor(self) -> list[Load]:
        """Loads that are charged or running right now."""
        out: list[Load] = []
        for state in (LoadState.CHARGED, LoadState.RUNNING):
            out.extend(self.loads.in_state(state))
        return sorted(out, key=lambda item: str(item.lot))

    def awaiting_disposition(self) -> list[Load]:
        return self.loads.in_state(LoadState.COMPLETE) + self.loads.in_state(LoadState.HELD)

    def furnace_history(self, furnace: FurnaceTag | str) -> list[Load]:
        return self.loads.on_furnace(furnace)

    def loads_in_doubt(self, report: Nonconformance) -> list[Load]:
        """Loads that finished inside an equipment report's suspect window."""
        if report.suspect_from is None or report.suspect_to is None:
            return []
        return self.loads.between(
            datetime.combine(report.suspect_from, time.min),
            datetime.combine(report.suspect_to, time.max),
        )

    def all_loads_in_doubt(self) -> dict[str, list[Load]]:
        """Every open report with a window, and what it catches."""
        caught: dict[str, list[Load]] = {}
        for report in self.reports.open_reports():
            if report.suspect_from is None:
                continue
            caught[report.number] = self.loads_in_doubt(report)
        return caught

    def reports_against_furnace(self, furnace: FurnaceTag | str) -> list[Nonconformance]:
        return self.reports.against(str(furnace))

    def counts(self) -> dict[str, int]:
        return {
            "furnaces": self.furnaces.count(),
            "thermocouples": self.sensors.count(),
            "certificates": self.sensors.certificates.count(),
            "loads": self.loads.count(),
            "pieces": self.loads.piece_count(),
            "nonconformances": self.reports.count(),
            "accuracy tests": self.sat.count(),
            "recipe revisions": self.recipes.count(),
        }

    def open_ncr_count(self) -> int:
        return len(self.reports.open_reports())

    def certified_between(self, start: date, end: date) -> list[Load]:
        window = self.loads.between(
            datetime.combine(start, time.min), datetime.combine(end, time.max)
        )
        return [item for item in window if item.state is LoadState.CERTIFIED]
