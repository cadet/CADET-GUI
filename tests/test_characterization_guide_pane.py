from __future__ import annotations

import html

from cadetgui.characterization_guide import DEFAULT_CHAIN, EXPERIMENT_TYPES, GLOSSARY
from cadetgui.widgets.composite.characterization_guide_pane import (
    CharacterizationGuideWidget,
    markdown_html,
)


def test_markdown_subset():
    out = markdown_html("# Title\n\nSome **bold**\ntext.\n\n1. one\n   more\n2. two\n\n- a\n- b\n")

    assert out == (
        "<h3>Title</h3><p>Some <b>bold</b> text.</p>"
        "<ol><li>one more</li><li>two</li></ol><ul><li>a</li><li>b</li></ul>"
    )
    assert markdown_html("a < b") == "<p>a &lt; b</p>"


def test_renders_the_workflow_the_glossary_and_every_experiment_type():
    guide = CharacterizationGuideWidget()

    assert "<h3>Characterizing a column, step by step</h3>" in guide.workflow.value
    assert guide.workflow.value.count("<li>") == 8
    for term, definition in GLOSSARY.items():
        assert f"<dt><b>{html.escape(term)}</b></dt>" in guide.glossary.value
        assert html.escape(definition) in guide.glossary.value
    for experiment in EXPERIMENT_TYPES.values():
        assert html.escape(experiment.label) in guide.experiment_types.value
        assert html.escape(experiment.what_you_run) in guide.experiment_types.value
    for step in DEFAULT_CHAIN:
        assert step.title in guide.chain.value


def test_lab_checks_are_listed_per_step_in_the_guide():
    from cadetgui.widgets.composite import CharacterizationGuideWidget

    text = CharacterizationGuideWidget().lab_checks.value
    assert "Lab checks the software cannot do" in text
    for step in DEFAULT_CHAIN:
        for item in step.advice:
            assert html.escape(item, quote=False) in text


def test_optimizer_choice_is_explained_in_the_guide():
    text = CharacterizationGuideWidget().optimizers.value
    assert "Nelder-Mead minimizes a single objective" in text and "U-NSGA-III" in text
