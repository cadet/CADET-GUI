"""Fixtures of the instrument domain: bound widgets, one cached simulation, stub runners."""
from __future__ import annotations

import shutil
import warnings

import matplotlib
import pytest

matplotlib.use("Agg")
warnings.filterwarnings("ignore", category=UserWarning)


@pytest.fixture
def bound(instrument_and_configuration):
    """`(instrument, configuration)`: a default InstrumentWidget and its ConfigurationWidget."""
    return instrument_and_configuration


@pytest.fixture
def instrument(bound):
    return bound[0]


@pytest.fixture
def configuration(bound):
    return bound[1]


@pytest.fixture(scope="session")
def simulated(tmp_path_factory):
    """`(result, h5 path)` of one real run of the default bound configuration."""
    from cadetgui.process_model.simulation import run_process
    from cadetgui.widgets.instrument import ConfigurationWidget, InstrumentWidget

    path = tmp_path_factory.mktemp("simulated") / "run.h5"
    process = ConfigurationWidget(instrument=InstrumentWidget()).process
    return run_process(process, file_path=path), path


class StubRunner:
    """Stands in for `run_process`: returns the cached result, or raises `error`."""

    def __init__(self, simulated):
        self.result, self._path = simulated
        self.calls = []
        self.error = None

    def __call__(self, process, file_path=None):
        self.calls.append(process)
        if self.error is not None:
            raise self.error
        if file_path is not None:
            shutil.copy(self._path, file_path)
        return self.result


@pytest.fixture
def runner(simulated):
    return StubRunner(simulated)


@pytest.fixture
def solution(runner, configuration):
    """A SolutionWidget with a stub runner, bound to the default configuration."""
    from cadetgui.widgets.instrument import SolutionWidget

    widget = SolutionWidget(runner=runner)
    widget.bind_to_config(configuration)
    return widget


@pytest.fixture
def upload():
    """Set an ipywidgets FileUpload's value as a browser upload would."""
    import datetime as dt

    def _upload(file_upload, name, content):
        data = memoryview(content.encode() if isinstance(content, str) else content)
        file_upload.value = (
            {
                "name": name, "type": "", "size": len(data),
                "last_modified": dt.datetime.now(), "content": data,
            },
        )

    return _upload
