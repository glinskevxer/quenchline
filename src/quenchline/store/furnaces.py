"""Reading and writing furnaces.

The repository is deliberately dumb: it turns a :class:`~quenchline.furnaces.record.Furnace`
into rows and back, and it does not know a single rule about furnaces. Every
rule lives in the domain object, which is why saving a furnace that would be
invalid is impossible rather than merely discouraged: the object could not have
been constructed.

Zones are written as a delete and reinsert rather than a diff. There are never
more than a handful of them and a diff is code that only runs on a rare path,
which is the code most likely to be wrong.
"""

from __future__ import annotations

from ..errors import ConflictError, NotFoundError
from ..furnaces.classes import FurnaceClass, InstrumentationType
from ..furnaces.record import Furnace, FurnaceStatus
from ..furnaces.zones import QualifiedRange, WorkZone
from ..identity import FurnaceTag
from ..measure import Volume
from ..temperature import Temperature
from .database import Database


def _key(tag: FurnaceTag | str) -> str:
    """Canonical text for a furnace tag, however it was written."""
    return str(tag if isinstance(tag, FurnaceTag) else FurnaceTag.parse(tag))


class FurnaceRepository:
    """Furnaces and their work zones."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, furnace: Furnace) -> None:
        if self.exists(furnace.tag):
            raise ConflictError("furnace", str(furnace.tag))
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO furnace (tag, furnace_class, instrumentation, status, "
                "qualified_low, qualified_high, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
                self._row(furnace),
            )
            self._write_zones(furnace)

    def save(self, furnace: Furnace) -> None:
        """Insert or replace, zones included."""
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO furnace (tag, furnace_class, instrumentation, "
                "status, qualified_low, qualified_high, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                self._row(furnace),
            )
            connection.execute(
                "DELETE FROM work_zone WHERE furnace_tag = ?", (str(furnace.tag),)
            )
            self._write_zones(furnace)

    def _row(self, furnace: Furnace) -> tuple[object, ...]:
        qualified = furnace.qualified
        return (
            str(furnace.tag),
            furnace.furnace_class.value,
            furnace.instrumentation.value,
            furnace.status.value,
            qualified.low.degf if qualified is not None else None,
            qualified.high.degf if qualified is not None else None,
            furnace.description,
        )

    def _write_zones(self, furnace: Furnace) -> None:
        for zone in furnace.zones:
            self.database.execute(
                "INSERT INTO work_zone (furnace_tag, name, cubic_feet, low_f, high_f) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(furnace.tag),
                    zone.name,
                    zone.volume.cubic_feet,
                    zone.low.degf,
                    zone.high.degf,
                ),
            )

    def exists(self, tag: FurnaceTag | str) -> bool:
        row = self.database.one("SELECT tag FROM furnace WHERE tag = ?", (_key(tag),))
        return row is not None

    def get(self, tag: FurnaceTag | str) -> Furnace:
        row = self.database.one(
            "SELECT tag, furnace_class, instrumentation, status, qualified_low, "
            "qualified_high, description FROM furnace WHERE tag = ?",
            (_key(tag),),
        )
        if row is None:
            raise NotFoundError("furnace", _key(tag))
        return self._build(row)

    def all(self) -> list[Furnace]:
        rows = self.database.query(
            "SELECT tag, furnace_class, instrumentation, status, qualified_low, "
            "qualified_high, description FROM furnace ORDER BY tag"
        )
        return [self._build(row) for row in rows]

    def of_class(self, furnace_class: FurnaceClass) -> list[Furnace]:
        rows = self.database.query(
            "SELECT tag FROM furnace WHERE furnace_class = ? ORDER BY tag",
            (furnace_class.value,),
        )
        return [self.get(row["tag"]) for row in rows]

    def in_service(self) -> list[Furnace]:
        rows = self.database.query(
            "SELECT tag FROM furnace WHERE status = ? ORDER BY tag",
            (FurnaceStatus.IN_SERVICE.value,),
        )
        return [self.get(row["tag"]) for row in rows]

    def delete(self, tag: FurnaceTag | str) -> None:
        if not self.exists(tag):
            raise NotFoundError("furnace", _key(tag))
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM work_zone WHERE furnace_tag = ?", (_key(tag),))
            connection.execute("DELETE FROM furnace WHERE tag = ?", (_key(tag),))

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM furnace")
        return int(row["n"]) if row is not None else 0

    def _zones(self, tag: str) -> tuple[WorkZone, ...]:
        rows = self.database.query(
            "SELECT name, cubic_feet, low_f, high_f FROM work_zone "
            "WHERE furnace_tag = ? ORDER BY name",
            (tag,),
        )
        return tuple(
            WorkZone(
                row["name"],
                Volume(row["cubic_feet"]),
                Temperature.fahrenheit(row["low_f"]),
                Temperature.fahrenheit(row["high_f"]),
            )
            for row in rows
        )

    def _build(self, row: object) -> Furnace:
        mapping = dict(row)  # type: ignore[call-overload]
        qualified = None
        if mapping["qualified_low"] is not None and mapping["qualified_high"] is not None:
            qualified = QualifiedRange(
                Temperature.fahrenheit(mapping["qualified_low"]),
                Temperature.fahrenheit(mapping["qualified_high"]),
            )
        return Furnace(
            tag=FurnaceTag.parse(mapping["tag"]),
            furnace_class=FurnaceClass(mapping["furnace_class"]),
            instrumentation=InstrumentationType(mapping["instrumentation"]),
            zones=self._zones(mapping["tag"]),
            qualified=qualified,
            status=FurnaceStatus(mapping["status"]),
            description=mapping["description"],
        )
