"""Reading and writing instruments and their calibration history.

Three tables, because a calibration has many points and an instrument has many
calibrations, and both of those are genuinely one to many rather than a list
that could live in a column.

As with the accuracy tests, no verdict is stored. Whether a calibration passed
falls out of the readings and the tolerance, and a tolerance tightened after the
fact should change the verdict on the old records rather than leaving a stored
"passed" that nothing agrees with any more.
"""

from __future__ import annotations

from datetime import date

from ..calendar_rules import DueRule, Interval, IntervalUnit
from ..errors import ConflictError, NotFoundError
from ..identity import InstrumentTag
from ..instruments.calibration import CalibrationCheck, InstrumentCalibration
from ..instruments.record import Instrument, InstrumentStatus
from ..instruments.register import InstrumentRegister
from ..instruments.types import Accuracy, InstrumentClass, InstrumentFunction, Readout, Span
from ..temperature import Scale, Temperature, TemperatureDelta
from .database import Database
from .keys import instrument_key as _key


class InstrumentRepository:
    """Instruments and everything that has been done to them."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, instrument: Instrument) -> None:
        if self.exists(instrument.tag):
            raise ConflictError("instrument", str(instrument.tag))
        self.save(instrument)

    def save(self, instrument: Instrument) -> None:
        accuracy = instrument.accuracy
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO instrument (tag, function, span_low_f, span_high_f, "
                "accuracy_percent, accuracy_basis, accuracy_floor_f, resolution_f, readout, "
                "interval_count, interval_unit, due_rule, status, make, model, serial) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(instrument.tag),
                    instrument.function.value,
                    instrument.span.low.degf,
                    instrument.span.high.degf,
                    accuracy.percent,
                    accuracy.basis.value,
                    accuracy.floor_f,
                    instrument.resolution.degf,
                    instrument.readout.value,
                    instrument.interval.count,
                    instrument.interval.unit.value,
                    instrument.due_rule.value,
                    instrument.status.value,
                    instrument.make,
                    instrument.model,
                    instrument.serial,
                ),
            )
        for calibration in instrument.calibrations:
            self.file(calibration)

    def file(self, calibration: InstrumentCalibration) -> None:
        """Store one calibration and its points."""
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO instrument_calibration (number, instrument_tag, "
                "performed, tolerance_f, technician, standard) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    calibration.number,
                    str(calibration.instrument),
                    calibration.performed.isoformat(),
                    calibration.tolerance.degf,
                    calibration.technician,
                    calibration.standard,
                ),
            )
            connection.execute(
                "DELETE FROM instrument_check WHERE calibration_number = ?",
                (calibration.number,),
            )
            for check in calibration.checks:
                connection.execute(
                    "INSERT INTO instrument_check (calibration_number, nominal_f, "
                    "as_found_f, as_left_f) VALUES (?, ?, ?, ?)",
                    (
                        calibration.number,
                        check.nominal.degf,
                        check.as_found.degf,
                        check.as_left.degf if check.as_left is not None else None,
                    ),
                )

    def exists(self, tag: InstrumentTag | str) -> bool:
        return (
            self.database.one("SELECT tag FROM instrument WHERE tag = ?", (_key(tag),))
            is not None
        )

    def get(self, tag: InstrumentTag | str) -> Instrument:
        row = self.database.one("SELECT * FROM instrument WHERE tag = ?", (_key(tag),))
        if row is None:
            raise NotFoundError("instrument", _key(tag))
        return self._build(row)

    def all(self) -> list[Instrument]:
        rows = self.database.query("SELECT * FROM instrument ORDER BY tag")
        return [self._build(row) for row in rows]

    def with_function(self, function: InstrumentFunction) -> list[Instrument]:
        rows = self.database.query(
            "SELECT * FROM instrument WHERE function = ? ORDER BY tag", (function.value,)
        )
        return [self._build(row) for row in rows]

    def register(self) -> InstrumentRegister:
        register = InstrumentRegister()
        for instrument in self.all():
            register.add(instrument)
        return register

    def delete(self, tag: InstrumentTag | str) -> None:
        if not self.exists(tag):
            raise NotFoundError("instrument", _key(tag))
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM instrument_check WHERE calibration_number IN "
                "(SELECT number FROM instrument_calibration WHERE instrument_tag = ?)",
                (_key(tag),),
            )
            connection.execute(
                "DELETE FROM instrument_calibration WHERE instrument_tag = ?", (_key(tag),)
            )
            connection.execute("DELETE FROM instrument WHERE tag = ?", (_key(tag),))

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM instrument")
        return int(row["n"]) if row is not None else 0

    def _calibrations(self, tag: str) -> tuple[InstrumentCalibration, ...]:
        rows = self.database.query(
            "SELECT * FROM instrument_calibration WHERE instrument_tag = ? "
            "ORDER BY performed, number",
            (tag,),
        )
        built: list[InstrumentCalibration] = []
        for row in rows:
            points = self.database.query(
                "SELECT nominal_f, as_found_f, as_left_f FROM instrument_check "
                "WHERE calibration_number = ? ORDER BY nominal_f",
                (row["number"],),
            )
            built.append(
                InstrumentCalibration(
                    number=row["number"],
                    instrument=InstrumentTag.parse(row["instrument_tag"]),
                    performed=date.fromisoformat(row["performed"]),
                    checks=tuple(
                        CalibrationCheck(
                            Temperature.fahrenheit(point["nominal_f"]),
                            Temperature.fahrenheit(point["as_found_f"]),
                            (
                                Temperature.fahrenheit(point["as_left_f"])
                                if point["as_left_f"] is not None
                                else None
                            ),
                        )
                        for point in points
                    ),
                    tolerance=TemperatureDelta(row["tolerance_f"], Scale.FAHRENHEIT),
                    technician=row["technician"],
                    standard=row["standard"],
                )
            )
        return tuple(built)

    def _build(self, row: object) -> Instrument:
        mapping = dict(row)  # type: ignore[call-overload]
        return Instrument(
            tag=InstrumentTag.parse(mapping["tag"]),
            function=InstrumentFunction(mapping["function"]),
            span=Span(
                Temperature.fahrenheit(mapping["span_low_f"]),
                Temperature.fahrenheit(mapping["span_high_f"]),
            ),
            accuracy=Accuracy(
                mapping["accuracy_percent"],
                InstrumentClass(mapping["accuracy_basis"]),
                mapping["accuracy_floor_f"],
            ),
            resolution=TemperatureDelta(mapping["resolution_f"], Scale.FAHRENHEIT),
            readout=Readout(mapping["readout"]),
            interval=Interval(
                mapping["interval_count"], IntervalUnit(mapping["interval_unit"])
            ),
            due_rule=DueRule(mapping["due_rule"]),
            status=InstrumentStatus(mapping["status"]),
            make=mapping["make"],
            model=mapping["model"],
            serial=mapping["serial"],
            calibrations=self._calibrations(mapping["tag"]),
        )
