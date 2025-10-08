"""Reading and writing system accuracy tests.

A SAT is stored as it was taken, not as it was judged. The verdict falls out of
the furnace class and the correction policy, both of which can change: a furnace
reclassified from class 3 to class 2 makes every one of its old tests harder,
and the shop wants to know that rather than reading a stored "passed" from two
years ago.

So the table holds six numbers and no verdict, and the history object judges
them on the way out.
"""

from __future__ import annotations

from datetime import date

from ..errors import ConflictError, NotFoundError
from ..furnaces.classes import FurnaceClass, InstrumentationType
from ..identity import FurnaceTag, InstrumentTag, SensorTag
from ..sat.model import SatMethod, SatReading, SatTest
from ..sat.schedule import SatHistory
from ..temperature import Scale, Temperature, TemperatureDelta
from .database import Database
from .keys import furnace_key


def _tag(value: str | None) -> SensorTag | None:
    return SensorTag.parse(value) if value else None


def _instrument(value: str | None) -> InstrumentTag | None:
    return InstrumentTag.parse(value) if value else None


def _delta(value: float) -> TemperatureDelta:
    return TemperatureDelta(value, Scale.FAHRENHEIT)


class SatRepository:
    """System accuracy tests, stored as taken."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, test: SatTest) -> None:
        if self.exists(test.number):
            raise ConflictError("system accuracy test", test.number)
        self.save(test)

    def save(self, test: SatTest) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO sat_test (number, furnace_tag, performed, "
                "setpoint_f, method, apply_corrections, technician, system_indicated_f, "
                "system_sensor_correction_f, system_instrument_correction_f, system_sensor, "
                "system_instrument, test_indicated_f, test_sensor_correction_f, "
                "test_instrument_correction_f, test_sensor, test_instrument) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    test.number,
                    str(test.furnace),
                    test.performed.isoformat(),
                    test.setpoint.degf,
                    test.method.value,
                    int(test.apply_corrections),
                    test.technician,
                    test.system.indicated.degf,
                    test.system.sensor_correction.degf,
                    test.system.instrument_correction.degf,
                    str(test.system.sensor) if test.system.sensor else None,
                    str(test.system.instrument) if test.system.instrument else None,
                    test.test.indicated.degf,
                    test.test.sensor_correction.degf,
                    test.test.instrument_correction.degf,
                    str(test.test.sensor) if test.test.sensor else None,
                    str(test.test.instrument) if test.test.instrument else None,
                ),
            )

    def exists(self, number: str) -> bool:
        return (
            self.database.one("SELECT number FROM sat_test WHERE number = ?", (number,))
            is not None
        )

    def get(self, number: str) -> SatTest:
        row = self.database.one("SELECT * FROM sat_test WHERE number = ?", (number,))
        if row is None:
            raise NotFoundError("system accuracy test", number)
        return self._build(row)

    def for_furnace(self, furnace: FurnaceTag | str) -> list[SatTest]:
        rows = self.database.query(
            "SELECT * FROM sat_test WHERE furnace_tag = ? ORDER BY performed, number",
            (furnace_key(furnace),),
        )
        return [self._build(row) for row in rows]

    def all(self) -> list[SatTest]:
        rows = self.database.query("SELECT * FROM sat_test ORDER BY performed, number")
        return [self._build(row) for row in rows]

    def furnaces(self) -> list[str]:
        rows = self.database.query(
            "SELECT DISTINCT furnace_tag FROM sat_test ORDER BY furnace_tag"
        )
        return [row["furnace_tag"] for row in rows]

    def history(
        self,
        furnace: FurnaceTag | str,
        furnace_class: FurnaceClass,
        instrumentation: InstrumentationType,
    ) -> SatHistory:
        """Rebuild a judged history for one furnace."""
        tag = furnace if isinstance(furnace, FurnaceTag) else FurnaceTag.parse(furnace)
        history = SatHistory(tag, furnace_class, instrumentation)
        for test in self.for_furnace(tag):
            history.file(test)
        return history

    def delete(self, number: str) -> None:
        if not self.exists(number):
            raise NotFoundError("system accuracy test", number)
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM sat_test WHERE number = ?", (number,))

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM sat_test")
        return int(row["n"]) if row is not None else 0

    def _build(self, row: object) -> SatTest:
        mapping = dict(row)  # type: ignore[call-overload]
        return SatTest(
            number=mapping["number"],
            furnace=FurnaceTag.parse(mapping["furnace_tag"]),
            performed=date.fromisoformat(mapping["performed"]),
            setpoint=Temperature.fahrenheit(mapping["setpoint_f"]),
            system=SatReading(
                Temperature.fahrenheit(mapping["system_indicated_f"]),
                _delta(mapping["system_sensor_correction_f"]),
                _delta(mapping["system_instrument_correction_f"]),
                _tag(mapping["system_sensor"]),
                _instrument(mapping["system_instrument"]),
            ),
            test=SatReading(
                Temperature.fahrenheit(mapping["test_indicated_f"]),
                _delta(mapping["test_sensor_correction_f"]),
                _delta(mapping["test_instrument_correction_f"]),
                _tag(mapping["test_sensor"]),
                _instrument(mapping["test_instrument"]),
            ),
            method=SatMethod(mapping["method"]),
            technician=mapping["technician"],
            apply_corrections=bool(mapping["apply_corrections"]),
        )
