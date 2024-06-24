"""The instrument register and the calibration schedule that falls out of it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..calendar_rules import days_until, is_overdue
from ..errors import ConflictError, NotFoundError
from ..identity import InstrumentTag
from ..temperature import Temperature
from .calibration import InstrumentCalibration, suspect_window
from .record import Instrument, InstrumentStatus
from .types import InstrumentFunction


@dataclass(frozen=True)
class DueEntry:
    """One line of the calibration schedule."""

    instrument: Instrument
    due: date | None
    days_left: int | None
    overdue: bool

    @property
    def never_calibrated(self) -> bool:
        return self.due is None


@dataclass
class InstrumentRegister:
    """Every instrument in the shop."""

    instruments: dict[str, Instrument] = field(default_factory=dict)

    def add(self, instrument: Instrument) -> None:
        key = str(instrument.tag)
        if key in self.instruments:
            raise ConflictError("instrument", key)
        self.instruments[key] = instrument

    def get(self, tag: InstrumentTag | str) -> Instrument:
        key = str(tag)
        if key not in self.instruments:
            raise NotFoundError("instrument", key)
        return self.instruments[key]

    def replace(self, instrument: Instrument) -> None:
        key = str(instrument.tag)
        if key not in self.instruments:
            raise NotFoundError("instrument", key)
        self.instruments[key] = instrument

    def file_calibration(self, calibration: InstrumentCalibration) -> Instrument:
        """Attach a calibration to the instrument it belongs to."""
        instrument = self.get(calibration.instrument)
        updated = instrument.with_calibration(calibration)
        self.instruments[str(instrument.tag)] = updated
        return updated

    def __len__(self) -> int:
        return len(self.instruments)

    def __contains__(self, tag: object) -> bool:
        return str(tag) in self.instruments

    def all(self) -> list[Instrument]:
        return [self.instruments[key] for key in sorted(self.instruments)]

    def in_service(self) -> list[Instrument]:
        return [i for i in self.all() if i.status is InstrumentStatus.IN_SERVICE]

    def with_function(self, function: InstrumentFunction) -> list[Instrument]:
        return [i for i in self.all() if i.function is function]

    def schedule(self, on: date, *, grace: int = 0) -> list[DueEntry]:
        """Every instrument, soonest due first, never calibrated ones first of all."""
        entries: list[DueEntry] = []
        for instrument in self.all():
            if instrument.status is InstrumentStatus.RETIRED:
                continue
            due = instrument.due_on()
            if due is None:
                entries.append(DueEntry(instrument, None, None, True))
                continue
            entries.append(
                DueEntry(
                    instrument,
                    due,
                    days_until(due, on),
                    is_overdue(due, on, grace=grace),
                )
            )
        entries.sort(
            key=lambda e: (e.due is not None, e.due or date.min, str(e.instrument.tag))
        )
        return entries

    def overdue(self, on: date, *, grace: int = 0) -> list[DueEntry]:
        return [e for e in self.schedule(on, grace=grace) if e.overdue]

    def due_within(self, on: date, days: int) -> list[DueEntry]:
        return [
            e for e in self.schedule(on) if e.days_left is not None and 0 <= e.days_left <= days
        ]

    def usable(
        self, function: InstrumentFunction, at: Temperature, on: date
    ) -> list[Instrument]:
        """Instruments that are in service, in calibration and good enough."""
        return [
            i
            for i in self.in_service()
            if i.in_calibration(on) and i.qualified_for(function, at)
        ]

    def suspect_work(self, tag: InstrumentTag | str) -> list[tuple[str, date, date]]:
        """Every window this instrument's history throws into doubt."""
        instrument = self.get(tag)
        windows: list[tuple[str, date, date]] = []
        for calibration in instrument.history:
            window = suspect_window(calibration, instrument.previous_to(calibration))
            if window is not None:
                windows.append((calibration.number, window[0], window[1]))
        return windows


def build_register(instruments: list[Instrument]) -> InstrumentRegister:
    register = InstrumentRegister()
    for instrument in instruments:
        register.add(instrument)
    return register
