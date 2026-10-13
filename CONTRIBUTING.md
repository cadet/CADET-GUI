# Contributing to **CADET-GUI**


## Environment Setup and Dependency Installation



## Code Requirements



### Coding Style

We use [`Ruff`](https://docs.astral.sh/ruff/) for linting and formatting all Python files.

```bash
pip install ruff
ruff check    # lint
ruff format   # format
```

### Unit Tests

```bash
pip install -e . --group dev
pytest              # fast default run, skips tests marked slow
pytest -m slow      # only the slow ones (real simulations and fits)
pytest -m ""        # everything, as CI does
```

The suite mirrors the package: `tests/<domain>/` for `process_model`, `instrument`,
`estimation`, `characterization`, `parameters`, `io` and `ui`, plus `tests/benches/`.
Shared fixtures are in `tests/conftest.py` (isolated configuration and run stores,
`pulse_process`, `instrument_and_configuration`, `synchronous_threads`); each folder adds
its own in a `conftest.py`. `tests/test_widget_contract.py` checks every top-level widget.

What a test should check: that a widget builds the right CADET-Process objects, wires to
other widgets, rejects invalid input and keeps its last valid state, round-trips through
save/load or snapshot/apply, and that `code()` reproduces the result. Prefer
`pytest.mark.parametrize` over one test per template or model. Layout, wording and styling
are not tested. Mark long simulations and fits `@pytest.mark.slow`.

Browser tests of the element views run in headless Chromium and are skipped when
Playwright or its browser is missing. CI (`.github/workflows/tests.yml`) runs the full
suite on every push to `main` and on pull requests.

### Pre-commit Hooks


## Issues vs. Pull Requests



## Branch Policy


## Documentation


## Versioning

CADET-GUI follows [CADET-Process](https://github.com/fau-advanced-separations/CADET-Process)'s
versioning: a plain `MAJOR.MINOR.PATCH` string in `cadetgui/__init__.py`'s
`__version__`, read dynamically by `pyproject.toml` — never duplicate it
elsewhere. Pre-1.0, a MINOR bump may include breaking changes; PATCH is
fixes only. Tag each release `vX.Y.Z`.

## Publish Package

Not yet automated. To cut a release: bump `__version__`, commit, tag the
commit `vX.Y.Z`, and create a GitHub release from that tag.
