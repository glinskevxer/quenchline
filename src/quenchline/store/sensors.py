"""Reading and writing thermocouples, their certificates and their usage.

Three tables and one rule worth naming: a **certificate is shared**, not owned.
Two couples calibrated in the same lab visit can be on the same certificate
number, and a certificate outlives the couple that was on it when a couple is
scrapped. So certificates are written once and referenced, and deleting a couple
never deletes a certificate.

Usage events are append only. Nothing in the shop legitimately un-runs a load,
and a repository that offers a way to delete a use is a repository somebody will
use to make a couple look younger than it is.
"""

from __future__ import annotations

from datetime import date

from ..errors import ConflictError, NotFoundError
from ..identity import SensorTag
from ..sensors.calibration import CalibrationPoint, Certificate, Convention
from ..sensors.record import Construction, SensorRole, SensorStatus, Thermocouple
from ..sensors.types import ThermocoupleType, ToleranceClass
from ..sensors.usage import UsageEvent, UsageLedger
from ..temperature import Scale, Temperature, TemperatureDelta
from ..timespan import Duration
from .database import Database


class CertificateRepository:
    """Calibration certificates, shared between couples."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save(self, certificate: Certificate) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO certificate "
                "(number, issued, convention, laboratory, accredited) VALUES (?, ?, ?, ?, ?)",
                (
                    certificate.number,
                    certificate.issued.isoformat(),
                    certificate.convention.value,
                    certificate.laboratory,
                    int(certificate.accredited),
                ),
            )
            connection.execute(
                "DELETE FROM certificate_point WHERE certificate_number = ?",
                (certificate.number,),
            )
            for point in certificate.points:
                connection.execute(
                    "INSERT INTO certificate_point (certificate_number, nominal_f, value_f) "
                    "VALUES (?, ?, ?)",
                    (certificate.number, point.nominal.degf, point.value.degf),
                )

    def exists(self, number: str) -> bool:
        return (
            self.database.one("SELECT number FROM certificate WHERE number = ?", (number,))
            is not None
        )

    def get(self, number: str) -> Certificate:
        row = self.database.one(
            "SELECT number, issued, convention, laboratory, accredited "
            "FROM certificate WHERE number = ?",
            (number,),
        )
        if row is None:
            raise NotFoundError("certificate", number)
        points = self.database.query(
            "SELECT nominal_f, value_f FROM certificate_point "
            "WHERE certificate_number = ? ORDER BY nominal_f",
            (number,),
        )
        return Certificate(
            number=row["number"],
            issued=date.fromisoformat(row["issued"]),
            points=tuple(
                CalibrationPoint(
                    Temperature.fahrenheit(p["nominal_f"]),
                    TemperatureDelta(p["value_f"], Scale.FAHRENHEIT),
                )
                for p in points
            ),
            convention=Convention(row["convention"]),
            laboratory=row["laboratory"],
            accredited=bool(row["accredited"]),
        )

    def numbers(self) -> list[str]:
        return [
            row["number"]
            for row in self.database.query("SELECT number FROM certificate ORDER BY number")
        ]

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM certificate")
        return int(row["n"]) if row is not None else 0


def _key(tag: SensorTag | str) -> str:
    """Canonical text for a tag, however it was written.

    ``TC-01`` and ``TC-00001`` are the same couple, and a caller typing the
    short form at a command line should not silently miss the record.
    """
    return str(tag if isinstance(tag, SensorTag) else SensorTag.parse(tag))


class SensorRepository:
    """Thermocouples and their usage ledgers."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.certificates = CertificateRepository(database)

    def insert(self, couple: Thermocouple) -> None:
        if self.exists(couple.tag):
            raise ConflictError("thermocouple", str(couple.tag))
        self.save(couple)

    def save(self, couple: Thermocouple) -> None:
        if couple.certificate is not None:
            self.certificates.save(couple.certificate)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO thermocouple (tag, kind, construction, role, "
                "grade, status, location, certificate_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(couple.tag),
                    couple.kind.value,
                    couple.construction.value,
                    couple.role.value,
                    couple.grade.value,
                    couple.status.value,
                    couple.location,
                    couple.certificate.number if couple.certificate is not None else None,
                ),
            )

    def exists(self, tag: SensorTag | str) -> bool:
        return (
            self.database.one("SELECT tag FROM thermocouple WHERE tag = ?", (_key(tag),))
            is not None
        )

    def get(self, tag: SensorTag | str) -> Thermocouple:
        row = self.database.one(
            "SELECT tag, kind, construction, role, grade, status, location, "
            "certificate_number FROM thermocouple WHERE tag = ?",
            (_key(tag),),
        )
        if row is None:
            raise NotFoundError("thermocouple", _key(tag))
        certificate = (
            self.certificates.get(row["certificate_number"])
            if row["certificate_number"]
            else None
        )
        return Thermocouple(
            tag=SensorTag.parse(row["tag"]),
            kind=ThermocoupleType(row["kind"]),
            construction=Construction(row["construction"]),
            role=SensorRole(row["role"]),
            grade=ToleranceClass(row["grade"]),
            status=SensorStatus(row["status"]),
            location=row["location"],
            certificate=certificate,
        )

    def all(self) -> list[Thermocouple]:
        rows = self.database.query("SELECT tag FROM thermocouple ORDER BY tag")
        return [self.get(row["tag"]) for row in rows]

    def in_role(self, role: SensorRole) -> list[Thermocouple]:
        rows = self.database.query(
            "SELECT tag FROM thermocouple WHERE role = ? ORDER BY tag", (role.value,)
        )
        return [self.get(row["tag"]) for row in rows]

    def uncalibrated(self) -> list[Thermocouple]:
        rows = self.database.query(
            "SELECT tag FROM thermocouple WHERE certificate_number IS NULL ORDER BY tag"
        )
        return [self.get(row["tag"]) for row in rows]

    def delete(self, tag: SensorTag | str) -> None:
        if not self.exists(tag):
            raise NotFoundError("thermocouple", _key(tag))
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM sensor_use WHERE sensor_tag = ?", (_key(tag),))
            connection.execute("DELETE FROM thermocouple WHERE tag = ?", (_key(tag),))

    def record_use(self, tag: SensorTag | str, event: UsageEvent) -> None:
        if not self.exists(tag):
            raise NotFoundError("thermocouple", _key(tag))
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO sensor_use "
                "(sensor_tag, used_on, peak_f, seconds, role, reference) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _key(tag),
                    event.on.isoformat(),
                    event.peak.degf,
                    event.at_temperature.seconds,
                    event.role.value,
                    event.reference,
                ),
            )

    def ledger(self, tag: SensorTag | str) -> UsageLedger:
        if not self.exists(tag):
            raise NotFoundError("thermocouple", _key(tag))
        rows = self.database.query(
            "SELECT used_on, peak_f, seconds, role, reference FROM sensor_use "
            "WHERE sensor_tag = ? ORDER BY used_on, id",
            (_key(tag),),
        )
        ledger = UsageLedger()
        for row in rows:
            ledger.record(
                UsageEvent(
                    date.fromisoformat(row["used_on"]),
                    Temperature.fahrenheit(row["peak_f"]),
                    Duration(row["seconds"]),
                    SensorRole(row["role"]),
                    row["reference"],
                )
            )
        return ledger

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM thermocouple")
        return int(row["n"]) if row is not None else 0
