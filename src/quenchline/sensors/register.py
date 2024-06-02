"""The thermocouple register, and whether a couple may be used for a job.

Eligibility is the first place in this codebase where several independent rules
have to agree, and where one rule decides which of the others even applies.

The shape of it:

* a couple must be **usable** at all, which is its status;
* it must be **rated** for the temperature the job runs at, which is its type;
* it must have **life left**, which is its ledger against its limit;
* and it must be **calibrated**, which is the interesting one, because whether
  a certificate is required at all depends on the role and the construction.

A permanently installed base metal control couple needs no certificate: the
system accuracy test covers it, and demanding one would stop every furnace in
the shop. The same couple moved to survey work needs a current certificate that
covers the survey temperature. Nothing about the couple changed. The job did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from ..calendar_rules import Interval
from ..errors import ConflictError, NotFoundError
from ..identity import SensorTag
from ..temperature import Temperature
from .record import Construction, SensorRole, SensorStatus, Thermocouple
from .types import ToleranceClass
from .usage import UsageEvent, UsageLedger, assess

DEFAULT_CALIBRATION_INTERVAL = Interval.years(1)
NOBLE_CALIBRATION_INTERVAL = Interval.years(2)


class Blocker(Enum):
    """Why a couple may not be used."""

    NOT_USABLE = "not_usable"
    OUT_OF_RANGE = "out_of_range"
    LIFE_SPENT = "life_spent"
    NO_CERTIFICATE = "no_certificate"
    CERTIFICATE_EXPIRED = "certificate_expired"
    CERTIFICATE_RANGE = "certificate_range"
    GRADE_TOO_LOOSE = "grade_too_loose"


@dataclass(frozen=True)
class Eligibility:
    """The answer, with every reason it was refused rather than just the first."""

    tag: SensorTag
    role: SensorRole
    blockers: tuple[Blocker, ...]
    detail: tuple[str, ...]

    @property
    def is_eligible(self) -> bool:
        return not self.blockers

    def __str__(self) -> str:
        if self.is_eligible:
            return f"{self.tag} may be used as a {self.role.value} sensor"
        return f"{self.tag} refused: " + ", ".join(self.detail)


def requires_certificate(construction: Construction, role: SensorRole) -> bool:
    """Whether a couple in this situation must carry a calibration certificate."""
    if role in {SensorRole.SURVEY, SensorRole.TEST}:
        return True
    if role.is_permanent:
        return False
    return not construction.is_expendable


def calibration_interval(couple: Thermocouple) -> Interval:
    return NOBLE_CALIBRATION_INTERVAL if couple.kind.is_noble else DEFAULT_CALIBRATION_INTERVAL


@dataclass
class SensorRegister:
    """Every couple in the shop, with its usage ledger."""

    couples: dict[str, Thermocouple] = field(default_factory=dict)
    ledgers: dict[str, UsageLedger] = field(default_factory=dict)

    def add(self, couple: Thermocouple) -> None:
        key = str(couple.tag)
        if key in self.couples:
            raise ConflictError("thermocouple", key)
        self.couples[key] = couple
        self.ledgers[key] = UsageLedger()

    def replace(self, couple: Thermocouple) -> None:
        key = str(couple.tag)
        if key not in self.couples:
            raise NotFoundError("thermocouple", key)
        self.couples[key] = couple

    def get(self, tag: SensorTag | str) -> Thermocouple:
        key = str(tag)
        if key not in self.couples:
            raise NotFoundError("thermocouple", key)
        return self.couples[key]

    def ledger(self, tag: SensorTag | str) -> UsageLedger:
        key = str(tag)
        if key not in self.ledgers:
            raise NotFoundError("thermocouple", key)
        return self.ledgers[key]

    def record_use(self, tag: SensorTag | str, event: UsageEvent) -> None:
        self.ledger(tag).record(event)

    def __len__(self) -> int:
        return len(self.couples)

    def __contains__(self, tag: object) -> bool:
        return str(tag) in self.couples

    def all(self) -> list[Thermocouple]:
        return [self.couples[key] for key in sorted(self.couples)]

    def in_role(self, role: SensorRole) -> list[Thermocouple]:
        return [c for c in self.all() if c.role is role]

    def in_service(self) -> list[Thermocouple]:
        return [c for c in self.all() if c.status is SensorStatus.IN_SERVICE]

    def check(
        self,
        tag: SensorTag | str,
        role: SensorRole,
        at: Temperature,
        on: date,
    ) -> Eligibility:
        """Whether one couple may be used in one role at one temperature."""
        couple = self.get(tag)
        blockers: list[Blocker] = []
        detail: list[str] = []

        if not couple.status.is_usable:
            blockers.append(Blocker.NOT_USABLE)
            detail.append(f"status is {couple.status.value}")

        if not couple.kind.covers(at):
            blockers.append(Blocker.OUT_OF_RANGE)
            detail.append(f"type {couple.kind.value} is not rated at {at.format()}")

        life = assess(couple.kind, couple.construction, role, self.ledger(tag))
        if life.is_spent:
            blockers.append(Blocker.LIFE_SPENT)
            detail.append(life.reason)

        needs_special = role is SensorRole.TEST and not couple.kind.is_noble
        if needs_special and couple.grade is not ToleranceClass.SPECIAL:
            blockers.append(Blocker.GRADE_TOO_LOOSE)
            detail.append("a base metal test couple must be special limits")

        if requires_certificate(couple.construction, role):
            certificate = couple.certificate
            if certificate is None:
                blockers.append(Blocker.NO_CERTIFICATE)
                detail.append("no calibration certificate")
            else:
                if certificate.is_expired(on, calibration_interval(couple)):
                    blockers.append(Blocker.CERTIFICATE_EXPIRED)
                    detail.append(f"certificate {certificate.number} has expired")
                if not certificate.is_single_point and not certificate.covers(at):
                    blockers.append(Blocker.CERTIFICATE_RANGE)
                    detail.append("certificate does not cover the working temperature")

        return Eligibility(couple.tag, role, tuple(blockers), tuple(detail))

    def eligible(self, role: SensorRole, at: Temperature, on: date) -> list[Thermocouple]:
        """Every couple that could take this job today."""
        return [c for c in self.all() if self.check(c.tag, role, at, on).is_eligible]

    def spent(self) -> list[Thermocouple]:
        out: list[Thermocouple] = []
        for couple in self.all():
            life = assess(
                couple.kind, couple.construction, couple.role, self.ledger(couple.tag)
            )
            if life.is_spent:
                out.append(couple)
        return out


def build_register(couples: list[Thermocouple]) -> SensorRegister:
    register = SensorRegister()
    for couple in couples:
        register.add(couple)
    return register
