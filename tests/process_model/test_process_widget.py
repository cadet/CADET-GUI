"""ProcessWidget: cycle time, events, process templates and inlet profiles."""
from __future__ import annotations

import numpy as np
import pytest
from cadetgui import ProcessWidget
from cadetgui.widgets.instrument.templates import available_templates
from cadetgui.widgets.process_model.profiles import PolynomialEditor

from .conftest import event_list, outlet_solution


@pytest.mark.parametrize(
    "text, cycle_time, error", [("900", 900, ""), ("-1", 600, "lower bound"),
                                ("abc", 600, "Enter a number")],
)
def test_cycle_time_is_edited_as_a_literal(pulse_process, text, cycle_time, error):
    widget = ProcessWidget(pulse_process)
    widget.cycle_time.value = text
    assert pulse_process.cycle_time == cycle_time
    assert error in widget.cycle_time.error


def test_process_widget_creates_a_process_from_a_flow_sheet(pulse_process):
    widget = ProcessWidget(pulse_process.flow_sheet, name="new", values={"cycle_time": 300})
    assert widget.process.name == "new"
    assert widget.process.flow_sheet is pulse_process.flow_sheet
    assert widget.process.cycle_time == 300


def _fill(editor, name, path, time, *state):
    editor.name.value = name
    editor.path.value = path
    editor.time.value = time
    if editor.editors:
        for field, text in zip(editor.editors[0].fields, state):
            field.value = text
    else:
        editor.value.value = state[0]
    editor.apply.click()


def test_event_editor_adds_edits_and_removes_events(pulse_process):
    widget = ProcessWidget(pulse_process)
    editor = widget.event_editor
    assert editor.table.option_labels == ["load", "wash"]

    editor.new.click()
    _fill(editor, "elute", "flow_sheet.inlet.c", "300", "2")
    assert pulse_process.events_dict["elute"].time == 300
    assert 'process.add_event("elute", "flow_sheet.inlet.c", [2], 300)' in widget.code()
    assert editor.table.value is None
    assert "Added 'elute'" in editor.status.value

    editor.table.value = "elute"
    assert editor.apply.description == "Save changes"
    editor.time.value = "200"
    editor.apply.click()
    assert pulse_process.events_dict["elute"].time == 200
    assert editor.table.value == "elute"

    editor.new.click()
    _fill(editor, "elute", "flow_sheet.inlet.c", "100", "0")
    assert "already exists" in editor.status.value
    editor.new.click()
    _fill(editor, "late", "flow_sheet.inlet.c", "soon", "0")
    assert "Enter a number" in editor.status.value
    editor.new.click()
    _fill(editor, "", "flow_sheet.inlet.c", "10", "0")
    assert "name" in editor.status.value
    assert len(pulse_process.events) == 3

    editor.table.value = "elute"
    editor.remove.click()
    assert [e.name for e in pulse_process.events] == ["load", "wash"]


def test_event_editor_keeps_an_event_whose_edit_fails(pulse_process):
    editor = ProcessWidget(pulse_process).event_editor
    _fill(editor, "reverse", "flow_sheet.column.flow_direction", "100", "-1")
    editor.table.value = "reverse"
    editor.value.value = "5"
    editor.apply.click()
    assert "one of" in editor.status.value
    assert pulse_process.events_dict["reverse"].state == -1


def test_event_editor_sets_a_gradient_that_the_code_reproduces(pulse_process):
    widget = ProcessWidget(pulse_process)
    editor = widget.event_editor
    editor.new.click()
    _fill(editor, "gradient", "flow_sheet.inlet.c", "120", "0", "0.005")
    assert pulse_process.events_dict["gradient"].state == [[0, 0.005]]

    namespace = {"flow_sheet": pulse_process.flow_sheet}
    exec(widget.code(), namespace)
    np.testing.assert_allclose(
        outlet_solution(pulse_process), outlet_solution(namespace["process"])
    )


def test_event_editor_edits_other_parameters_as_values_and_follows_code(pulse_process):
    widget = ProcessWidget(pulse_process)
    editor = widget.event_editor
    editor.new.click()
    _fill(editor, "reverse", "flow_sheet.column.flow_direction", "100", "-1")
    assert pulse_process.events_dict["reverse"].state == -1

    pulse_process.add_event("rinse", "flow_sheet.inlet.c", [0.5], 300)
    widget.refresh()
    editor.table.value = "rinse"
    assert editor.time.value == "300"
    assert editor.editors[0].coefficients()[0] == 0.5


def test_templates_are_offered_only_for_an_lc_flow_sheet(pulse_process, lc_process):
    assert "Step" in available_templates(lc_process.flow_sheet)
    assert ProcessWidget(pulse_process).mode.layout.display == "none"
    assert ProcessWidget(lc_process).mode.layout.display == ""


def test_template_mode_writes_the_template_events_into_the_same_process(lc_process):
    from CADETProcess.instruments import Breakthrough

    widget = ProcessWidget(lc_process)
    seen = []
    widget.add_listener(seen.append)
    widget.mode.value = "Template"
    templates = widget.template_editor
    templates.picker.value = "Step"
    assert widget.process is lc_process and seen[-1] is lc_process
    assert [e.name for e in lc_process.events] == ["phase_0_B"]

    namespace = {"flow_sheet": lc_process.flow_sheet}
    exec(widget.code(), namespace)
    assert event_list(namespace["process"]) == event_list(lc_process)

    templates.picker.value = "Breakthrough"
    reference = Breakthrough("reference", lc_process.flow_sheet, **templates.values())
    assert event_list(reference) == event_list(lc_process)

    widget.mode.value = "Raw events"
    assert "process.add_event(" in widget.code()
    assert "phase_0_F" in widget.event_editor.table.option_labels


@pytest.mark.parametrize("name, index", [("c", 0), ("flow_rate", None)])
def test_polynomial_editor_edits_one_profile(pulse_process, name, index):
    inlet = pulse_process.flow_sheet.inlet
    calls = []
    editor = PolynomialEditor(inlet, name, index, process=pulse_process,
                              on_change=lambda: calls.append(1))
    assert editor.preview.selected_index is None
    before = editor.chart.value
    editor.fields[1].value = "0.01"
    assert editor.coefficients()[1] == 0.01
    profile = getattr(inlet, name)
    assert np.ravel(profile[index] if index is not None else profile)[1] == 0.01
    assert calls == [1]
    assert editor.chart.value != before
    assert editor.preview.selected_index is None
    editor.preview.selected_index = 0
    assert editor.preview.children == (editor.chart,)

    editor.fields[2].value = "x"
    assert editor.fields[2].error
    assert editor.coefficients()[2] == 0


def test_event_editor_returns_to_a_new_event_after_adding(pulse_process):
    """Entering a second event right after adding one must not overwrite the first."""
    editor = ProcessWidget(pulse_process).event_editor
    editor.new.click()
    _fill(editor, "elute", "flow_sheet.inlet.c", "300", "2")
    assert editor.apply.description == "Add event"
    assert editor.name.value == ""
    _fill(editor, "final_wash", "flow_sheet.inlet.c", "400", "0")
    assert pulse_process.events_dict["elute"].time == 300
    assert pulse_process.events_dict["final_wash"].time == 400
    assert editor.table.option_labels == ["load", "wash", "elute", "final_wash"]
