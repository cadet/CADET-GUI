"""The contract every top-level widget keeps: a Widget with a root, display and listeners."""

import ipywidgets as W
import pytest
from cadetgui.characterization.study import Study
from cadetgui.widgets import Widget
from cadetgui.widgets.benches import (
    CharacterizationWorkbenchWidget,
    InstrumentWorkbenchWidget,
)
from cadetgui.widgets.characterization import (
    CharacterizationGuideWidget,
    CharacterizationSetupWidget,
    CharacterizationStepWidget,
    ComparisonsWidget,
    ParameterStoreWidget,
    StudyComponentsWidget,
)
from cadetgui.widgets.estimation import ParameterEstimationWidget
from cadetgui.widgets.instrument import (
    ConfigurationWidget,
    DataImportWidget,
    InstrumentWidget,
    RunHistoryWidget,
    SolutionWidget,
)
from cadetgui.widgets.process_model import (
    ComponentSystemWidget,
    FlowSheetWidget,
    ProcessWidget,
    SimulationWidget,
    UnitOperationsWidget,
    UnitOperationWidget,
)
from CADETProcess.processModel import ComponentSystem, FlowSheet, Inlet


def _component_system():
    return ComponentSystem(["A"])


FACTORIES = {
    "ComponentSystemWidget": lambda p: ComponentSystemWidget(p.component_system),
    "UnitOperationsWidget": lambda p: UnitOperationsWidget(
        p.component_system, {u.name: u for u in p.flow_sheet.units}
    ),
    "UnitOperationWidget": lambda p: UnitOperationWidget(p.flow_sheet.column),
    "FlowSheetWidget": lambda p: FlowSheetWidget(p.flow_sheet),
    "ProcessWidget": lambda p: ProcessWidget(p),
    "SimulationWidget": lambda p: SimulationWidget(p),
    "InstrumentWidget": lambda p: InstrumentWidget(),
    "ConfigurationWidget": lambda p: ConfigurationWidget(),
    "SolutionWidget": lambda p: SolutionWidget(process=p),
    "RunHistoryWidget": lambda p: RunHistoryWidget(),
    "DataImportWidget": lambda p: DataImportWidget(),
    "ParameterEstimationWidget": lambda p: ParameterEstimationWidget(),
    "CharacterizationSetupWidget": lambda p: CharacterizationSetupWidget(Study()),
    "StudyComponentsWidget": lambda p: StudyComponentsWidget(Study()),
    "ComparisonsWidget": lambda p: ComparisonsWidget(Study()),
    "CharacterizationStepWidget": lambda p: CharacterizationStepWidget(Study()),
    "ParameterStoreWidget": lambda p: ParameterStoreWidget(Study()),
    "CharacterizationGuideWidget": lambda p: CharacterizationGuideWidget(),
    "InstrumentWorkbenchWidget": lambda p: InstrumentWorkbenchWidget(),
    "CharacterizationWorkbenchWidget": lambda p: CharacterizationWorkbenchWidget(),
}


# Widgets still to be moved onto the Widget base class; remove a name once it is.
NOT_YET_WIDGET = {
    "InstrumentWidget", "SolutionWidget", "RunHistoryWidget", "DataImportWidget",
    "InstrumentWorkbenchWidget",
}


@pytest.fixture(
    params=[
        pytest.param(name, marks=pytest.mark.xfail(reason="not yet a Widget"))
        if name in NOT_YET_WIDGET
        else name
        for name in sorted(FACTORIES)
    ]
)
def widget(request, pulse_process):
    return FACTORIES[request.param](pulse_process)


def test_widget_is_a_widget_with_a_root(widget):
    assert isinstance(widget, Widget)
    assert isinstance(widget.root, W.Widget)
    assert "application/vnd.jupyter.widget-view+json" in widget._repr_mimebundle_()


def test_widget_listeners_are_called_on_notify(widget):
    seen = []
    widget.add_listener(lambda *args: seen.append(args))
    widget._notify()
    assert seen == [()]


def test_object_widgets_edit_the_given_objects_in_place():
    component_system = _component_system()
    widget = ComponentSystemWidget(component_system)
    widget.field.value = ["A", "B"]
    assert widget.get_value() is component_system
    assert component_system.names == ["A", "B"]

    flow_sheet = FlowSheet(component_system, "flow_sheet")
    flow_sheet.add_unit(Inlet(component_system, "inlet"))
    assert FlowSheetWidget(flow_sheet).get_value() is flow_sheet
