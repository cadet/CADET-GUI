from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

import ipywidgets as W

from ...parameters.specs import require_positive
from ..elements import ChoiceField, EventTimelineChart, FloatField
from ..forms import FormRenderer
from ..process_model.timeline import show_timeline
from ..ui.layout import SettingsPopover, section, titled_header

__all__ = ["ProcessSection"]


_CYCLE_TIME_SLIDER_MAX_SECONDS = 300.0 * 60.0


def _push_to_slider(slider: W.FloatSlider, value: Any) -> None:
    """Show a typed value on `slider`, widening its range instead of clamping the value."""
    try:
        value = _round_10sf(float(value))
    except (TypeError, ValueError):
        return
    if value > slider.max:
        slider.max = value * 2
    slider.value = max(value, slider.min)


def _round_10sf(v: float) -> float:
    """Round to 10 significant figures, clearing browser-slider float noise."""
    return float(f"{v:.10g}")


class ProcessSection:
    """The process-template picker, its method form with event sliders, and the event timeline.

    `components` returns the component names the timeline labels its series with.
    """

    def __init__(self, *, options: list, components: Callable[[], Sequence[str]]) -> None:
        self._components = components
        self.form: Optional[FormRenderer] = None
        self.event_sliders: dict[str, W.FloatSlider] = {}
        self.cycle_time_minutes_element: Optional[FloatField] = None

        self.cycle_time_unit_checkbox = W.Checkbox(
            description="Show Cycle Time in Minutes", value=False, indent=False
        )
        self.cycle_time_unit_checkbox.observe(
            lambda _c: self._apply_cycle_time_unit_display(), names="value"
        )
        self.settings = SettingsPopover(
            tooltip="Process display settings",
            children=[self.cycle_time_unit_checkbox],
            visible=False,
        )
        self.picker = ChoiceField(label="Process Template:", options=options)
        self.form_box = W.VBox([])
        self._event_plot_label = W.HTML(
            "<div class='cadetgui-section-title'>Event Timeline</div>"
        )
        self.chart = EventTimelineChart()

        form_column = W.VBox([self.form_box])
        form_column.add_class("cadetgui-section-wide")
        chart_column = W.VBox([self._event_plot_label, self.chart])
        chart_column.add_class("cadetgui-section-half")
        columns = W.HBox([form_column, chart_column])
        columns.add_class("cadetgui-row")
        self.root = section(
            [
                titled_header("Process", self.settings.button),
                self.settings.box,
                self.picker,
                columns,
            ]
        )

    def clear(self) -> None:
        """Remove the method form from view and empty the timeline."""
        self.form_box.children = ()
        self.event_sliders = {}
        self.cycle_time_minutes_element = None
        show_timeline(self.chart, None, ())

    def show_form(self) -> None:
        """Show the method form with a slider beside each scalar field, and draw its timeline."""
        self.form_box.children = (self.form.root,)
        self.rebuild_event_sliders()

    def rebuild_event_sliders(self) -> None:
        """Link a slider to each scalar float field; a slider move commits like typing does."""
        self.event_sliders = {}
        self.cycle_time_minutes_element = None
        fields = self.form.spec.fields
        self.settings.visible = any(f.name == "cycle_time" for f in fields)

        for f in fields:
            if f.kind != "float":
                continue
            el = self.form.element(f.name)
            default = float(el.value)
            if f.name == "cycle_time":
                slider_max = max(default, _CYCLE_TIME_SLIDER_MAX_SECONDS)
            else:
                slider_max = default * 5 if default > 0 else 1.0
            # The default must sit on the step grid, or the browser snaps it and reports it back.
            step = default / 100 if default > 0 else 0.01
            slider = W.FloatSlider(
                value=default,
                min=0.0,
                max=slider_max,
                step=step,
                readout=False,
                layout=W.Layout(width="100%", max_width="200px", min_width="90px"),
            )
            # dlink + rounding rather than link: slider drags report float noise.
            W.dlink((slider, "value"), (el, "value"), transform=_round_10sf)
            el.observe(lambda change, s=slider: _push_to_slider(s, change["new"]), names="value")
            slider.observe(lambda _change: self.redraw(), names="value")
            self.event_sliders[f.name] = slider

        name_of = {id(self.form.element(f.name)): f.name for f in fields}
        children = []
        for child in self.form.root.children:
            name = name_of.get(id(child))
            extras = []
            if name == "cycle_time":
                extras.append(self._make_cycle_time_unit_toggle(child))
            if name in self.event_sliders:
                extras.append(self.event_sliders[name])
            if extras:
                # Wrap rather than overlap the slider on a narrow window.
                children.append(
                    W.HBox(
                        [child, *extras],
                        layout=W.Layout(flex_flow="row wrap", align_items="center"),
                    )
                )
            else:
                children.append(child)
        self.form.root.children = tuple(children)

        self._event_plot_label.layout.display = "" if self.event_sliders else "none"
        self.redraw()

    def _make_cycle_time_unit_toggle(self, seconds_element: Any) -> Any:
        """Return a minutes companion of the cycle-time field, kept in sync in both directions."""
        minutes_element = FloatField(
            label=seconds_element.label,
            value=float(seconds_element.value) / 60.0,
            units=r"\mathrm{min}",
            validate=require_positive,
        )
        W.dlink(
            (seconds_element, "value"), (minutes_element, "value"), transform=lambda s: s / 60.0
        )
        W.dlink(
            (minutes_element, "value"), (seconds_element, "value"), transform=lambda m: m * 60.0
        )
        self.cycle_time_minutes_element = minutes_element
        self._apply_cycle_time_unit_display()
        return minutes_element

    def _apply_cycle_time_unit_display(self) -> None:
        if self.cycle_time_minutes_element is None or self.form is None:
            return
        seconds_element = self.form.element("cycle_time")
        show_minutes = self.cycle_time_unit_checkbox.value
        seconds_element.layout.display = "none" if show_minutes else ""
        self.cycle_time_minutes_element.layout.display = "" if show_minutes else "none"

    def redraw(self) -> None:
        """Redraw the chart from the form's already-committed build, if there is one."""
        if self.form is None or self.form.built is None:
            return
        show_timeline(
            self.chart, self.form.built, self._components(), self.form.spec.phase_names,
        )
