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

## Layout

    src/quenchline/    the package
    tests/             the test suite

## Running the checks

    ruff check .
    ruff format --check .
    mypy
    pytest
