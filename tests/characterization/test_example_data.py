"""The synthetic Äkta-style example study and the script that generates it."""
from __future__ import annotations

import filecmp
import importlib.util
import json
import sys

import pytest
from cadetgui.characterization.comparison import Comparison, recipe_from_dict
from cadetgui.characterization.parameter_store import ParameterStore
from cadetgui.characterization.runner import StepSetup, build
from cadetgui.characterization.stages import describe_stage, write_targets
from cadetgui.instrument.process_builder import build_process
from cadetgui.io.experimental_data import is_akta_format, read_experimental_csv

from characterization.synthetic import DATA_DIR, MANIFEST

GENERATOR = DATA_DIR.parents[1] / "generate_characterization_chain_data.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location(GENERATOR.stem, GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text())


@pytest.fixture(scope="module")
def stores(gen):
    step1 = gen.step1_store(gen.initial_store())
    return step1, gen.step2_store(step1)


@pytest.fixture(scope="module")
def comparisons(manifest):
    return {raw["name"]: Comparison.from_dict(raw, base_dir=DATA_DIR)
            for raw in manifest["comparisons"]}


def test_steps_reference_declared_comparisons_and_bounds_contain_the_truth(manifest):
    names = {c["name"] for c in manifest["comparisons"]}
    for step in manifest["steps"]:
        assert step["comparisons"] and set(step["comparisons"]) <= names
        targets = write_targets(describe_stage(step["stage"], **step["options"]))
        for name, (lb, ub) in step["bounds"].items():
            assert lb < step["truth"][targets[name]] < ub, name


def test_every_data_file_reads_as_akta_with_its_channel_and_marker(manifest):
    for raw in manifest["comparisons"]:
        content = (DATA_DIR / raw["data_file"]).read_bytes()
        assert is_akta_format(content), raw["name"]
        run = read_experimental_csv(content, raw["name"])
        assert run.x_basis == "volume" and raw["channel"] in run.channels
        assert any(text.startswith(raw["injection_marker"]) for _, text in run.markers)
        assert build_process(recipe_from_dict(raw["recipe"]), overrides=raw["overrides"])


def test_generator_matches_the_manifest(gen, manifest):
    initial = ParameterStore.from_dict(manifest["initial_store"], gen.SPECS)
    for path, entry in gen.initial_store().entries.items():
        assert initial.entries[path].value == entry.value
    tubing, bed = (step["truth"] for step in manifest["steps"])
    assert tubing == {
        "flow_sheet.tubing_pre_column.length": gen.TUBING_PRE_COLUMN_LENGTH,
        "flow_sheet.tubing_pre_column.axial_dispersion": gen.TUBING_PRE_COLUMN_AXIAL_DISPERSION,
    }
    assert bed == {
        "flow_sheet.column.bed_porosity": gen.BED_POROSITY,
        "flow_sheet.column.particle_porosity": gen.PARTICLE_POROSITY,
        "flow_sheet.column.axial_dispersion": gen.COLUMN_AXIAL_DISPERSION,
    }


def test_steps_build_from_the_manifest(manifest, comparisons, stores):
    for raw, store, n_variables in zip(manifest["steps"], stores, (2, 3)):
        built = build(StepSetup.from_dict(raw, comparisons), store)
        assert built.problem.n_variables == n_variables


@pytest.mark.slow
def test_comparisons_match_their_truth_and_need_their_baseline_window(
    manifest, comparisons, stores
):
    step1, step2 = stores
    for name, comparison in comparisons.items():
        assert comparison.problems() == [], name
        store = step1 if name.startswith("System") else step2
        assert comparison.evaluate(store).value < 0.05, name

    raw = dict(next(r for r in manifest["comparisons"]
                    if r["name"] == "Small tracer pulse 1 (conductivity)"))
    raw["baseline_window"] = None
    with pytest.raises(ValueError):
        Comparison.from_dict(raw, base_dir=DATA_DIR).evaluate(step2)


@pytest.mark.slow
def test_generator_is_byte_deterministic(gen, tmp_path):
    out_a, out_b = tmp_path / "a", tmp_path / "b"
    for out_dir in (out_a, out_b):
        gen.OUT_DIR = out_dir
        gen.build_manifest()
    files = sorted(p.name for p in out_a.iterdir())
    assert files == sorted(p.name for p in out_b.iterdir())
    assert filecmp.cmpfiles(out_a, out_b, files, shallow=False)[1] == []
