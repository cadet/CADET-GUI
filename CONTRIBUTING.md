# Contributing to **CADET-GUI**


## Environment Setup and Dependency Installation



## Code Requirements



### Coding Style

We use the [`Ruff` linter / formatter](https://docs.astral.sh/ruff/formatter/) for all Python files.
To install the latest version of Ruff, use the following command:


```bash
pip install ruff
```

**Linting:** To check your files for compliance with our coding standards, run the following command:

```bash
ruff check
```

This command will analyze the specified directory and report any issues that need to be addressed.

**Formatting:** To automatically format your files according to our coding standards, use:

```bash
ruff format
```

This command will apply the necessary formatting changes to ensure consistency across the codebase.

### Unit Tests

Install the dev dependencies and run the suite with [pytest](https://docs.pytest.org/):

```bash
pip install -e ".[dev]"
pytest
```

Slow tests (real optimizer runs) are marked `@pytest.mark.slow`; skip them
during day-to-day work with `pytest -m "not slow"`, but run the full suite,
slow tests included, before opening a pull request.

### Pre-commit Hooks


## Issues vs. Pull Requests



## Branch Policy


## Documentation


## Versioning

CADET-GUI follows the same versioning approach as
[CADET-Process](https://github.com/fau-advanced-separations/CADET-Process):
a plain `MAJOR.MINOR.PATCH` string in `__version__`
(`cadetgui/__init__.py`), the single source of truth `pyproject.toml` reads
dynamically (`[tool.setuptools.dynamic] version = { attr =
"cadetgui.__version__" }`) — never duplicate the version number elsewhere.
While the project is pre-1.0, a MINOR bump may still include breaking
changes; PATCH is for fixes only. Tag each release `vX.Y.Z` to match.

## Publish Package

Not yet automated. To cut a release: bump `__version__`, commit, tag the
commit `vX.Y.Z`, and create a GitHub release from that tag.
