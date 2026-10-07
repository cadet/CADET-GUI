"""Checks for the synthetic Äkta-style characterization chain example data.

`examples/generate_characterization_chain_data.py` is loaded by path (it lives under
`examples/`, not the `cadetgui` package) and exercised directly against
`cadetgui.comparison.Comparison` and `cadetgui.characterization_runner.StepSetup`, the
same way a real consumer of `examples/data/characterization_akta/` would use it.
"""
from __future__ import annotations

import filecmp
import importlib.util
import json
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from cadetgui.characterization_runner import StepSetup, build  # noqa: E402
from cadetgui.comparison import Comparison, recipe_from_dict  # noqa: E402
from cadetgui.experimental_data import (  # noqa: E402
    is_akta_format,
    read_experimental_csv,
)
from cadetgui.process_builder import build_process  # noqa: E402

EXAMPLES_DIR = Path(__file__).parents[1] / "examples"
DATA_DIR = EXAMPLES_DIR / "data" / "characterization_akta"
GENERATOR_PATH = EXAMPLES_DIR / "generate_characterization_chain_data.py"
GENERATOR_NAME = "generate_characterization_chain_data"


def _load_generator():
    spec = importlib.util.spec_from_file_location(GENERATOR_NAME, GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolves string annotations via sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


@pytest.fixture(scope="module")
def manifest():
    with open(DATA_DIR / "manifest.json") as handle:
        return json.load(handle)


def test_manifest_parses(manifest):
    assert set(manifest) == {"description", "initial_store", "steps", "comparisons", "components"}
    assert len(manifest["steps"]) == 2
    assert {c["name"] for c in manifest["comparisons"]} == {
        "System pulse 1 (UV)",
        "System pulse 2 (UV)",
        "Small tracer pulse 1 (conductivity)",
        "Small tracer pulse 2 (conductivity)",
        "Large tracer pulse 1 (UV)",
        "Large tracer pulse 2 (UV)",
    }
    for step in manifest["steps"]:
        assert step["comparisons"], f"step {step['name']!r} has no comparisons"
        assert step["truth"], f"step {step['name']!r} has no truth"
        for path in step["truth"]:
            assert path.startswith("flow_sheet."), path


def test_manifest_steps_reference_declared_comparisons(manifest):
    names = {c["name"] for c in manifest["comparisons"]}
    for step in manifest["steps"]:
        assert set(step["comparisons"]) <= names


def test_bounds_contain_the_truth(manifest):
    """Bounds are keyed by variable name (`CharacterizeBase._default_variables()`'s
    `"name"`), truth by parameter path; both steps declare both consistently."""
    tubing_step, bed_step = manifest["steps"]

    tubing_bounds = tubing_step["bounds"]
    lb, ub = tubing_bounds["tubing_pre_column_length"]
    assert lb < tubing_step["truth"]["flow_sheet.tubing_pre_column.length"] < ub
    lb, ub = tubing_bounds["tubing_pre_column_axial_dispersion"]
    assert lb < tubing_step["truth"]["flow_sheet.tubing_pre_column.axial_dispersion"] < ub

    bed_bounds = bed_step["bounds"]
    lb, ub = bed_bounds["bed_porosity"]
    assert lb < bed_step["truth"]["flow_sheet.column.bed_porosity"] < ub
    lb, ub = bed_bounds["particle_porosity"]
    assert lb < bed_step["truth"]["flow_sheet.column.particle_porosity"] < ub
    lb, ub = bed_bounds["axial_dispersion"]
    assert lb < bed_step["truth"]["flow_sheet.column.axial_dispersion"] < ub


def test_every_comparison_reads_as_akta_with_channel_and_marker(manifest):
    for raw in manifest["comparisons"]:
        content = (DATA_DIR / raw["data_file"]).read_bytes()
        assert is_akta_format(content), raw["name"]
        run = read_experimental_csv(content, raw["name"])
        assert run.x_basis == "volume"
        assert raw["channel"] in run.channels, (raw["name"], list(run.channels))
        marker = raw["injection_marker"]
        assert any(text.startswith(marker) for _, text in run.markers), (
            raw["name"], run.markers,
        )
        if raw["components"]:
            assert set(raw["components"]) <= set(raw["recipe"]["components"])


def test_recipes_rebuild(manifest):
    for raw in manifest["comparisons"]:
        state = recipe_from_dict(raw["recipe"])
        process = build_process(state, overrides=raw["overrides"])
        assert process.check_config()
        assert len(state.components) == 1


def test_generator_stores_chain_matches_manifest(gen, manifest):
    """`gen.step1_store`/`gen.step2_store` are what the manifest's own truth/initial_store
    encode; a store built independently from the manifest's JSON must agree."""
    from cadetgui.parameter_store import ParameterStore

    initial = ParameterStore.from_dict(manifest["initial_store"], gen.SPECS)
    for path, entry in gen.initial_store().entries.items():
        assert initial.entries[path].value == entry.value

    tubing_truth = manifest["steps"][0]["truth"]
    bed_truth = manifest["steps"][1]["truth"]
    assert tubing_truth == {
        "flow_sheet.tubing_pre_column.length": gen.TUBING_PRE_COLUMN_LENGTH,
        "flow_sheet.tubing_pre_column.axial_dispersion": gen.TUBING_PRE_COLUMN_AXIAL_DISPERSION,
    }
    assert bed_truth == {
        "flow_sheet.column.bed_porosity": gen.BED_POROSITY,
        "flow_sheet.column.particle_porosity": gen.PARTICLE_POROSITY,
        "flow_sheet.column.axial_dispersion": gen.COLUMN_AXIAL_DISPERSION,
    }


@pytest.mark.slow
def test_generator_is_byte_deterministic(gen, tmp_path):
    """Regenerating (recipe -> build_process -> apply_store -> CADET-Core simulation ->
    Äkta shaping) twice, independently, gives byte-identical output -- the same check
    that rebuilding each process from its recipe, `initial_store` and truth reproduces
    the clean simulated signal exactly, since a mismatch anywhere in that chain would
    change the shaped CSV bytes.
    """
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    for out_dir in (out_a, out_b):
        gen.OUT_DIR = out_dir
        gen.build_manifest()

    files_a = sorted(p.name for p in out_a.iterdir())
    files_b = sorted(p.name for p in out_b.iterdir())
    assert files_a == files_b
    mismatch = filecmp.cmpfiles(out_a, out_b, files_a, shallow=False)[1]
    assert mismatch == []


@pytest.mark.slow
def test_comparisons_have_no_problems_and_evaluate_near_noise_level(gen, manifest):
    """Every comparison builds and simulates cleanly, and matches its own truth."""
    comparisons = {
        raw["name"]: Comparison.from_dict(raw, base_dir=DATA_DIR)
        for raw in manifest["comparisons"]
    }
    step1 = gen.step1_store(gen.initial_store())
    step2 = gen.step2_store(step1)
    store_by_name = {
        "System pulse 1 (UV)": step1,
        "System pulse 2 (UV)": step1,
        "Small tracer pulse 1 (conductivity)": step2,
        "Small tracer pulse 2 (conductivity)": step2,
        "Large tracer pulse 1 (UV)": step2,
        "Large tracer pulse 2 (UV)": step2,
    }

    for name, comparison in comparisons.items():
        assert comparison.problems() == [], name
        preview = comparison.evaluate(store_by_name[name])
        assert preview.value < 0.05, (name, preview.value)


@pytest.mark.slow
def test_missing_baseline_window_breaks_the_drifting_run(gen, manifest):
    """`Small tracer pulse 1 (conductivity)`'s explicit `baseline_window` is load-bearing:
    without it, the default whole-trace baseline fit fails on the pre-injection dip (too few
    points survive its lowest-2.5% threshold), demonstrating why the window is set in the
    manifest."""
    name = "Small tracer pulse 1 (conductivity)"
    raw = dict(next(r for r in manifest["comparisons"] if r["name"] == name))
    raw["baseline_window"] = None
    comparison = Comparison.from_dict(raw, base_dir=DATA_DIR)
    store = gen.step2_store(gen.step1_store(gen.initial_store()))
    with pytest.raises(ValueError):
        comparison.evaluate(store)


@pytest.mark.slow
def test_steps_build_with_characterization_runner(gen, manifest):
    """The manifest's steps build through `StepSetup.from_dict` + `build`, the same
    entry point a real characterization run would use."""
    comparisons = {
        raw["name"]: Comparison.from_dict(raw, base_dir=DATA_DIR)
        for raw in manifest["comparisons"]
    }
    step1 = gen.step1_store(gen.initial_store())
    step2 = gen.step2_store(step1)

    tubing_setup = StepSetup.from_dict(manifest["steps"][0], comparisons)
    built = build(tubing_setup, step1)
    assert built.problem.n_variables == 2

    bed_setup = StepSetup.from_dict(manifest["steps"][1], comparisons)
    built = build(bed_setup, step2)
    assert built.problem.n_variables == 3
