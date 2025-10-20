# quenchline

Pyrometry and process records for a commercial heat treating shop.

A shop runs steel through furnaces on a written thermal cycle, and every part of
that has to be defensible on paper: the thermocouple that read the part, the
instrument that recorded it, the survey that proved the furnace was uniform, and
the test that proved the metal came out right.

This is the register those measurements land in, and the engine that decides
whether a load is certifiable, which furnace is out of survey, and which
thermocouple has run past its usable life.

Everything is a command line tool over one SQLite file. There is no server.

## What is in it

| area | what it decides |
| --- | --- |
| `sensors` | thermocouple types, calibration certificates, correction factors, drift, and how much life a couple has left |
| `instruments` | accuracy and resolution, what an instrument is good enough for, and what an as found failure invalidates behind it |
| `furnaces` | class and instrumentation type, work zones, survey sensor counts, and the qualified operating range |
| `sat` | system accuracy tests, corrections on both sides, and the window a failure throws into doubt |
| `tus` | uniformity surveys, the stabilisation clock, sensor dropouts, and the range a survey earns |
| `recipes` | thermal cycles as ordered steps, with revision control and one released revision at a time |
| `loads` | the charge record, the datalogger trace, the deviation engine and the disposition that falls out |
| `quench` | media, baths, and whether one is fit to take a particular load |
| `hardness` | scales, conversion inside the published overlap, sampling plans and retests |
| `schedule` | one board for everything that comes due, ranked by what being late blocks |
| `report` | certificates of conformance, compliance summaries, and the four numbers the shop is measured on |

## Getting started

```
pip install -e ".[dev]"
quenchline --database shop.sqlite db status
```

Every command takes `--database`, `--today` and `--actor`. The date is an option
rather than a call to the system clock, so a report can be regenerated exactly
as it looked on the day it was signed.

```
quenchline --database shop.sqlite furnace add HT-04 --class 3 --instrumentation D
quenchline --database shop.sqlite furnace zone HT-04 main --cubic-feet 40 --low 1000F --high 1800F
quenchline --database shop.sqlite furnace wire HT-04 TC-01 --role control
quenchline --database shop.sqlite analyse choose --at 1550F --band 25
```

## Layout

    src/quenchline/    the package
    tests/             the test suite

## Running the checks

    ruff check .
    ruff format --check .
    mypy
    pytest
