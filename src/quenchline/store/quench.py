"""Reading and writing quench baths.

The medium is stored on the bath row rather than in a table of its own. That
looks like denormalising and it is deliberate: two tanks of the same oil
genuinely have different operating bands when one is a small integral quench and
the other is a big open tank, and a shared medium row would make changing one
change the other.

What a bath was last measured at is stored with it, because a bath has exactly
one current reading and keeping a history of readings in this table would mean
every query needing a subselect for the latest one.
"""

from __future__ import annotations

from datetime import date

from ..calendar_rules import Interval, IntervalUnit
from ..errors import ConflictError, NotFoundError
from ..quench.bath import Bath
from ..quench.media import Agitation, Medium, MediumKind
from ..temperature import Scale, Temperature, TemperatureDelta
from ..tolerance import Band
from .database import Database


class BathRepository:
    """Quench baths and what they were last measured at."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, bath: Bath) -> None:
        if self.exists(bath.identifier):
            raise ConflictError("quench bath", bath.identifier)
        self.save(bath)

    def save(self, bath: Bath) -> None:
        medium = bath.medium
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO quench_bath (identifier, medium_name, medium_kind, "
                "setpoint_f, band_f, minimum_agitation, concentration_low, "
                "concentration_high, melting_point_f, gallons, temperature_f, agitation, "
                "concentration, last_checked, check_interval_count, check_interval_unit, "
                "in_service) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bath.identifier,
                    medium.name,
                    medium.kind.value,
                    medium.operating.setpoint.degf,
                    medium.operating.plus.degf,
                    medium.minimum_agitation.value,
                    medium.concentration_low,
                    medium.concentration_high,
                    medium.melting_point.degf if medium.melting_point else None,
                    bath.gallons,
                    bath.temperature.degf,
                    bath.agitation.value,
                    bath.concentration,
                    bath.last_checked.isoformat() if bath.last_checked else None,
                    bath.check_interval.count,
                    bath.check_interval.unit.value,
                    int(bath.in_service),
                ),
            )

    def exists(self, identifier: str) -> bool:
        return (
            self.database.one(
                "SELECT identifier FROM quench_bath WHERE identifier = ?", (identifier,)
            )
            is not None
        )

    def get(self, identifier: str) -> Bath:
        row = self.database.one("SELECT * FROM quench_bath WHERE identifier = ?", (identifier,))
        if row is None:
            raise NotFoundError("quench bath", identifier)
        return self._build(row)

    def all(self) -> list[Bath]:
        rows = self.database.query("SELECT * FROM quench_bath ORDER BY identifier")
        return [self._build(row) for row in rows]

    def in_service(self) -> list[Bath]:
        rows = self.database.query(
            "SELECT * FROM quench_bath WHERE in_service = 1 ORDER BY identifier"
        )
        return [self._build(row) for row in rows]

    def of_kind(self, kind: MediumKind) -> list[Bath]:
        rows = self.database.query(
            "SELECT * FROM quench_bath WHERE medium_kind = ? ORDER BY identifier",
            (kind.value,),
        )
        return [self._build(row) for row in rows]

    def delete(self, identifier: str) -> None:
        if not self.exists(identifier):
            raise NotFoundError("quench bath", identifier)
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM quench_bath WHERE identifier = ?", (identifier,))

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM quench_bath")
        return int(row["n"]) if row is not None else 0

    def _build(self, row: object) -> Bath:
        mapping = dict(row)  # type: ignore[call-overload]
        medium = Medium(
            name=mapping["medium_name"],
            kind=MediumKind(mapping["medium_kind"]),
            operating=Band.symmetric(
                Temperature.fahrenheit(mapping["setpoint_f"]),
                TemperatureDelta(mapping["band_f"], Scale.FAHRENHEIT),
            ),
            minimum_agitation=Agitation(mapping["minimum_agitation"]),
            concentration_low=mapping["concentration_low"],
            concentration_high=mapping["concentration_high"],
            melting_point=(
                Temperature.fahrenheit(mapping["melting_point_f"])
                if mapping["melting_point_f"] is not None
                else None
            ),
        )
        return Bath(
            identifier=mapping["identifier"],
            medium=medium,
            gallons=mapping["gallons"],
            temperature=Temperature.fahrenheit(mapping["temperature_f"]),
            agitation=Agitation(mapping["agitation"]),
            concentration=mapping["concentration"],
            last_checked=(
                date.fromisoformat(mapping["last_checked"]) if mapping["last_checked"] else None
            ),
            check_interval=Interval(
                mapping["check_interval_count"],
                IntervalUnit(mapping["check_interval_unit"]),
            ),
            in_service=bool(mapping["in_service"]),
        )
