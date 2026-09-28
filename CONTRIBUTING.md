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
pytest
```

Slow tests (real optimizer runs) are marked `@pytest.mark.slow`; skip them
locally with `pytest -m "not slow"`, but run the full suite before opening a
pull request. CI (`.github/workflows/tests.yml`) runs the full suite,
including headless-browser element tests, on every push to `main` and PR.

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
