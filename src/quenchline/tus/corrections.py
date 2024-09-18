"""Applying corrections to raw survey data.

The recorder writes what the couples told it. Before any of that can be judged
against a fifteen degree band, two known errors have to come out of it: the
correction on each survey couple's own certificate, and the correction on the
instrument that read them all.

The order does not matter, they are added, but **completeness** does. A survey
where seven couples are corrected and two are not is not a corrected survey, and
it is not an uncorrected one either. It is a mixture, and the two uncorrected
couples are quietly carrying an error the other seven have had removed. That is
why the default policy here refuses rather than skipping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..errors import OutOfRangeError, ValidationError
from ..sensors.calibration import Certificate
from ..temperature import Scale, Temperature, TemperatureDelta
from .survey import Scan, Survey, SurveySetpoint


class MissingPolicy(Enum):
    """What to do about a sensor with no usable certificate."""

    REFUSE = "refuse"
    LEAVE_RAW = "leave_raw"

    @property
    def is_strict(self) -> bool:
        return self is MissingPolicy.REFUSE


@dataclass
class CorrectionSet:
    """Every correction that applies to one survey."""

    certificates: dict[str, Certificate] = field(default_factory=dict)
    instrument: Certificate | None = None
    policy: MissingPolicy = MissingPolicy.REFUSE

    def add(self, key: str, certificate: Certificate) -> None:
        if key in self.certificates:
            raise ValidationError(f"{key} already has a certificate", field="key")
        self.certificates[key] = certificate

    def covers(self, key: str) -> bool:
        return key in self.certificates

    def missing_for(self, keys: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(key for key in keys if key not in self.certificates)

    def correction(self, key: str, reading: Temperature) -> TemperatureDelta:
        """The total correction for one sensor at one reading."""
        total = 0.0
        certificate = self.certificates.get(key)
        if certificate is None:
            if self.policy.is_strict:
                raise ValidationError(
                    f"no calibration certificate for survey sensor {key}", field="certificates"
                )
        else:
            total += _correction_or_raise(certificate, reading, key).degf
        if self.instrument is not None:
            total += _correction_or_raise(self.instrument, reading, "instrument").degf
        return TemperatureDelta(total, Scale.FAHRENHEIT)

    def apply(self, key: str, reading: Temperature) -> Temperature:
        return reading + self.correction(key, reading)


def _correction_or_raise(
    certificate: Certificate, reading: Temperature, who: str
) -> TemperatureDelta:
    try:
        return certificate.correction_at(reading)
    except OutOfRangeError as error:
        raise ValidationError(
            f"certificate {certificate.number} for {who} does not reach {reading.format()}",
            field="certificates",
        ) from error


def correct_scan(scan: Scan, corrections: CorrectionSet) -> Scan:
    return Scan(
        scan.elapsed,
        tuple((key, corrections.apply(key, value)) for key, value in scan.values),
    )


def correct_setpoint(data: SurveySetpoint, corrections: CorrectionSet) -> SurveySetpoint:
    return SurveySetpoint(
        data.setpoint, tuple(correct_scan(scan, corrections) for scan in data.scans)
    )


def correct_survey(survey: Survey, corrections: CorrectionSet) -> Survey:
    """Return the same survey with every reading corrected."""
    missing = corrections.missing_for(survey.keys)
    if missing and corrections.policy.is_strict:
        raise ValidationError(
            "no calibration certificate for survey sensor " + ", ".join(missing),
            field="certificates",
        )
    return Survey(
        survey.number,
        survey.furnace,
        survey.zone,
        survey.performed,
        survey.points,
        tuple(correct_setpoint(data, corrections) for data in survey.setpoints),
        survey.instrument,
        survey.technician,
        (*survey.notes, "corrections applied"),
    )
