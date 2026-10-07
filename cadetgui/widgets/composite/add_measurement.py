"""The add-measurement stepper of the Measurements pane."""

from __future__ import annotations

import copy
import dataclasses
import html
import math
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import ipywidgets as W

from ...characterization_guide import (
    CHAIN_BY_ID,
    COMPONENT_ROLES,
    DEFAULT_CHAIN,
    EXPERIMENT_TYPES,
    SALT,
    SALT_ROLE,
    ExperimentType,
    find_injection_marker,
    measurement_from_run,
    role_fix,
    with_implied_values,
)
from ...comparison import Comparison
from ...configuration_store import ConfigurationState
from ...experimental_data import ExperimentalRun
from ...process_builder import check_recipe
from ...study import Study
from .._help import term_html
from .._status import status_html
from ..elements import (
    ChoiceField,
    ChromatogramChart,
    SelectableTable,
    TextField,
)
from ._measurement_common import (
    _ML_PER_MIN,
    _check_float,
    _detector_hint,
    _format,
    _note,
    _observed_unit,
    _optional_float,
    _recipe_flow_rate,
    _row,
    _same,
    _template_options,
    _title,
    component_options,
    observation_label,
    problems_html,
    recipe_summary_html,
    recipe_with_template,
)
from ._measurement_upload import _RunUpload
from .system_diagram import recipe_diagram_svg

if TYPE_CHECKING:
    pass


_OTHER = "__other__"
_NEW = "__new__"
_MAX_PREVIEW_POINTS = 2000

_PAGES = ("Upload", "Channel", "Experiment type", "Details", "Confirm")


class AddMeasurementFlow(_RunUpload):
    """In-pane stepper: data file → channel → experiment type → details → a new comparison.

    Started for a step (or one of its experiment types), the experiment-type page is
    skipped: the Details page shows the step's type, or a choice among its types
    preselected by the channel's detector when that is unambiguous.

    `runs()` lists already loaded runs by data file; `base_recipe()` returns the recipe
    to start from and a sentence saying where it comes from; `on_added(comparison,
    notes)` is called after the comparison is in `study`.
    """

    def __init__(
        self,
        study: Study,
        *,
        runs: Callable[[], Dict[str, Optional[ExperimentalRun]]],
        base_recipe: Callable[[], Tuple[Optional[ConfigurationState], str]],
        on_added: Callable[[Comparison, List[str]], None],
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self.study = study
        self._runs = runs
        self._base_recipe = base_recipe
        self._on_added = on_added
        self._on_change = on_change
        self._start_step: Optional[str] = None
        self._fixed_step: Optional[str] = None
        self._visible_pages: Tuple[int, ...] = tuple(range(len(_PAGES)))
        self._default_type: Optional[str] = None
        self._typed_for_channel: Optional[str] = None
        self._type_chosen = False
        self._title = W.HTML()
        self.page = 0
        self._prefilled_for: Optional[Tuple[Any, ...]] = None
        self._loading = False

        upload_page = self._init_upload()

        self._channel = ChoiceField(label="Channel:")
        self._channel_chart = ChromatogramChart(view_width=480, view_height=200, y_label="Signal")
        self._markers = _note()

        self._type_table = SelectableTable(
            columns=["Feeds step", "Experiment type", "Detector"],
            empty_text="No experiment types.",
        )
        self._type_help = W.HTML()
        self._other_template = ChoiceField(label="Process template:")
        self._other_template_note = _note(
            "Runs added as “Other” get no experiment type, so pick the process (method) "
            "the run followed. It starts with the template's default timing and "
            "concentrations; change them under Advanced after adding."
        )
        self._other_template_box = W.VBox(
            [_row(self._other_template), self._other_template_note],
            layout=W.Layout(display="none"),
        )

        self._step_type = W.RadioButtons(layout=W.Layout(width="auto"))
        self._step_type.add_class("cadetgui-step-type")
        self._step_type_info = W.HTML()
        self._step_type_box = W.VBox([self._step_type_info, self._step_type],
                                     layout=W.Layout(display="none"))

        self._name = TextField(label="Name:", validate=self._check_name)
        self._component = ChoiceField(label="Component:")
        self._new_component = TextField(label="New component:",
                                        validate=self._check_new_component)
        self._new_role = ChoiceField(label="Role:")
        self._component_note = _note()
        self._role_fix = W.HTML()
        self._role_fix_target: Optional[Tuple[str, str]] = None
        self._btn_role_fix = W.Button(
            icon="exchange", button_style="warning",
            layout=W.Layout(width="auto", display="none"),
        )
        self._btn_role_fix.on_click(lambda _b: self.make_component_fit())
        self._flow_rate = TextField(label="Flow rate:", units="mL/min", validate=_check_float)
        self._marker = ChoiceField(label="Injection marker:")
        self._details_note = _note()

        self._base_note = W.HTML()
        self._summary = W.HTML()
        self._diagram = W.HTML()
        self._confirm_problems = W.HTML()
        self._implied = W.Checkbox(
            value=False, indent=False,
            description="Also add the values this experiment type assumes to the parameter store",
            layout=W.Layout(width="auto"),
        )
        self._implied_note = _note()

        self._progress = W.HTML()
        self._btn_back = W.Button(description="Back", icon="arrow-left")
        self._btn_next = W.Button(description="Next", icon="arrow-right", button_style="primary")
        self._btn_add = W.Button(description="Add measurement", icon="check",
                                 button_style="success")
        self._btn_cancel = W.Button(description="Cancel", icon="times")
        self.status = W.HTML()
        self.status.add_class("cadetgui-status")

        self._channel.observe(lambda _c: self._show_channel(), names="selected_index")
        self._type_table.observe(lambda _c: self._show_type_help(), names="selected_index")
        self._type_table.observe(lambda _c: self._target_changed(), names="selected_index")
        self._component.observe(lambda _c: self._sync_new_component(), names="selected_index")
        self._new_component.observe(lambda _c: self._refresh_role_fix(), names="value")
        self._step_type.observe(self._on_step_type, names="value")
        self._btn_back.on_click(lambda _b: self.back())
        self._btn_next.on_click(lambda _b: self.next())
        self._btn_add.on_click(lambda _b: self.confirm())
        self._btn_cancel.on_click(lambda _b: self.close())

        self._pages = [
            upload_page,
            W.VBox([
                _note("Pick the detector channel this measurement compares against."),
                _row(self._channel),
                self._channel_chart,
                self._markers,
            ]),
            W.VBox([
                _note("What did you run? The experiment type sets the flow path, process "
                      "template and observation point, and which characterization step the "
                      "measurement feeds. Types matching the channel's detector are marked."),
                self._type_table,
                self._type_help,
                self._other_template_box,
            ]),
            W.VBox([
                self._step_type_box,
                _row(self._name, self._component),
                _row(self._new_component, self._new_role),
                self._component_note,
                _row(self._role_fix, self._btn_role_fix),
                _row(self._flow_rate, self._marker),
                self._details_note,
            ]),
            W.VBox([
                self._base_note,
                _title(term_html("recipe", "Recipe") + " of the new measurement"),
                self._summary,
                self._diagram,
                self._confirm_problems,
                self._implied,
                self._implied_note,
            ]),
        ]
        nav = W.HBox([self._btn_back, self._btn_next, self._btn_add, self._btn_cancel])
        nav.add_class("cadetgui-toolbar")
        self.root = W.VBox([
            self._title,
            self._progress,
            *self._pages,
            self.status,
            nav,
        ])
        self.root.add_class("cadetgui-section")
        self.root.layout.display = "none"

    # Navigation

    @property
    def is_open(self) -> bool:
        """Whether the stepper is shown."""
        return self.root.layout.display != "none"

    def start(
        self, *, step_id: Optional[str] = None, experiment_type: Optional[str] = None
    ) -> None:
        """Open the stepper at the upload page.

        With a `step_id` or an `experiment_type` of a chain step, the experiment-type page
        is left out and the type is picked among that step's types on the Details page.
        An explicit `experiment_type` is preselected; with only a `step_id`, the channel's
        detector decides when it matches exactly one of the step's types, otherwise the
        step's first type is used.
        """
        self._explicit_type = experiment_type
        if experiment_type is None and step_id in CHAIN_BY_ID:
            experiment_type = CHAIN_BY_ID[step_id].experiment_types[0]
        self._start_step = step_id if step_id in CHAIN_BY_ID else (
            EXPERIMENT_TYPES[experiment_type].step_id if experiment_type in EXPERIMENT_TYPES
            else None
        )
        guide = CHAIN_BY_ID.get(self._start_step or "")
        fixed = guide is not None and experiment_type in guide.experiment_types
        self._fixed_step = self._start_step if fixed else None
        self._default_type = experiment_type if fixed else None
        self._typed_for_channel = None
        self._type_chosen = False
        self._visible_pages = (0, 1, 3, 4) if fixed else tuple(range(len(_PAGES)))
        self._step_type_box.layout.display = "" if fixed else "none"
        self.run, self.data_file, self._pending = None, "", None
        self._roles_box.children = ()
        self._run_note.value = ""
        self._prefilled_for = None
        self._implied.value = False
        self.status.value = ""
        self._other_template.set_options([], keep_value=False)
        options: List[Tuple[str, Optional[str]]] = [("Choose…", None)]
        options += [(key, key) for key, run in self._runs().items() if run is not None]
        self._loading = True
        try:
            self._loaded.set_options(options, keep_value=False)
            self._fill_types(experiment_type)
        finally:
            self._loading = False
        self.root.layout.display = ""
        self._go(0)
        self._target_changed()

    def close(self) -> None:
        """Hide the stepper without adding anything."""
        self.root.layout.display = "none"
        self._target_changed()

    @property
    def target_step(self) -> Optional[str]:
        """The chain step the measurement being added feeds, if known."""
        experiment_type = self.experiment_type
        if experiment_type is not None:
            return experiment_type.step_id
        if self._type_table.value == _OTHER:
            return None
        return self._start_step

    def _target_changed(self) -> None:
        guide = CHAIN_BY_ID.get(self.target_step or "")
        target = (
            f" for the step <b>{html.escape(guide.title)}</b>" if guide is not None
            else " (not assigned to a step)" if self._type_table.value == _OTHER
            else ""
        )
        self._title.value = (
            "<div class='cadetgui-panel-title'>Add a " + term_html("measurement")
            + target + "</div>"
        )
        if self._on_change is not None:
            self._on_change()

    @property
    def pages(self) -> List[str]:
        """The names of the pages this stepper walks through."""
        return [_PAGES[i] for i in self._visible_pages]

    def _step_by(self, delta: int) -> None:
        pages = self._visible_pages
        index = pages.index(self.page) if self.page in pages else 0
        self._go(pages[min(max(index + delta, 0), len(pages) - 1)])

    def back(self) -> None:
        """Go to the previous page."""
        self._step_by(-1)

    def next(self) -> None:
        """Go to the next page if the current one is complete."""
        error = self._page_error()
        if error:
            self.status.value = status_html("error", error)
            return
        self._step_by(1)

    def _go(self, page: int) -> None:
        self.page = page
        self.status.value = ""
        if page == 1:
            self._fill_channels()
        elif page == 2:
            self._fill_types(self._type_table.value)
        elif page == 3:
            self._fill_step_types()
            self._prefill_details()
        elif page == 4:
            self._show_confirm()
        for i, box in enumerate(self._pages):
            box.layout.display = "" if i == page else "none"
        self._btn_back.disabled = page == 0
        self._btn_next.layout.display = "none" if page == len(_PAGES) - 1 else ""
        self._btn_add.layout.display = "" if page == len(_PAGES) - 1 else "none"
        self._progress.value = " › ".join(
            f"<b>{n} {_PAGES[i]}</b>" if i == page else f"{n} {_PAGES[i]}"
            for n, i in enumerate(self._visible_pages, start=1)
        )

    def _page_error(self) -> Optional[str]:
        if self.page == 0 and self.run is None:
            return "Upload a data file or pick a loaded run first."
        if self.page == 1 and self._channel.value is None:
            return "Pick a channel."
        if self.page == 2 and self._type_table.value is None:
            return "Pick what you ran (the experiment type)."
        if self.page == 3:
            fields = [self._name, self._flow_rate]
            if self._component.value == _NEW:
                fields.append(self._new_component)
            invalid = [f.label.rstrip(":") for f in fields if not f.is_valid]
            if invalid:
                return f"Fix {', '.join(invalid)} first."
            if self.experiment_type is not None and self._component.value is None:
                return "Pick the component you injected."
            text, target = self._component_role_fix()
            if text and self._component.value != _NEW:
                return text + (
                    " Change its role with the button, or pick another component."
                    if target is not None else ""
                )
        return None

    # 2 Channel

    def _fill_channels(self) -> None:
        channels = list(self.run.channels) if self.run is not None else []
        self._loading = True
        try:
            self._channel.set_options([(c, c) for c in channels])
        finally:
            self._loading = False
        self._show_channel()

    def _show_channel(self) -> None:
        run, channel = self.run, self._channel.value
        if run is None or channel not in run.channels:
            self._channel_chart.series = []
            return
        trace = run.channels[channel]
        stride = max(1, math.ceil(trace.x.size / _MAX_PREVIEW_POINTS))
        volume = run.x_basis == "volume"
        self._channel_chart.x_label = f"{'Volume' if volume else 'Time'} / {run.x_unit}"
        self._channel_chart.x_name = "V" if volume else "t"
        self._channel_chart.x_unit = run.x_unit
        self._channel_chart.y_label = trace.unit or channel
        self._channel_chart.series = [{
            "name": channel,
            "times": trace.x[::stride].tolist(),
            "values": trace.values[::stride].tolist(),
            "reference": True,
        }]
        self._markers.value = (
            "Markers found in the run log: " + ", ".join(
                html.escape(f"{text} @ {x:g} {run.x_unit}") for x, text in run.markers
            ) if run.markers else "No run-log markers in this file; the injection position "
            "can be entered by hand under Advanced after adding."
        )

    # 3 Experiment type

    def _fill_types(self, select: Optional[str]) -> None:
        hint = _detector_hint(self._channel.value or "")
        options: List[Tuple[str, str]] = []
        rows: List[List[Any]] = []
        chained = [t for g in DEFAULT_CHAIN for t in g.experiment_types]
        unchained = [t for t in EXPERIMENT_TYPES if t not in chained]
        for type_id in (*chained, *unchained):
            experiment_type = EXPERIMENT_TYPES[type_id]
            guide = CHAIN_BY_ID.get(experiment_type.step_id)
            detector: Any = experiment_type.detector
            if hint is not None and hint == experiment_type.detector:
                detector = (f"{experiment_type.detector} · matches channel", "ok")
            options.append((experiment_type.label, type_id))
            rows.append([guide.title if guide else "Not assigned to a step",
                         experiment_type.label, detector])
        options.append(("Other: set up everything by hand", _OTHER))
        rows.append(["Not assigned to a step", "Other: set up everything by hand", "–"])
        was_loading = self._loading
        self._loading = True
        try:
            self._type_table.set_options(options, rows=rows, select_none=True)
            if select is not None:
                self._type_table.value = select
        finally:
            self._loading = was_loading
        self._show_type_help()

    def _show_type_help(self) -> None:
        type_id = self._type_table.value
        self._other_template_box.layout.display = "" if type_id == _OTHER else "none"
        if type_id is None:
            self._type_help.value = ""
            return
        if type_id == _OTHER:
            self._fill_other_templates()
            self._type_help.value = (
                "<p class='cadetgui-note'>The run uses your System setup with the process "
                "template picked below. Set the observation point, probe and everything "
                "else under Advanced after adding. The measurement is not assigned to a "
                "step until you set an experiment type.</p>"
            )
            return
        experiment_type = EXPERIMENT_TYPES[type_id]
        guide = CHAIN_BY_ID.get(experiment_type.step_id)
        parts = [
            f"<p><b>What you run:</b> {html.escape(experiment_type.what_you_run)}</p>",
            f"<p><b>Feeds step:</b> {html.escape(guide.title if guide else 'none')} · "
            f"<b>{term_html('probe', 'Probe')}:</b> {html.escape(experiment_type.probe_role)}"
            f" · <b>{term_html('observation point', 'Observation point')}:</b> "
            f"{html.escape(observation_label(experiment_type.solution_path))} "
            f"({html.escape(experiment_type.detector)})</p>",
        ]
        if experiment_type.help:
            parts.append(f"<p class='cadetgui-note'>{html.escape(experiment_type.help)}</p>")
        self._type_help.value = "".join(parts)

    def _fill_other_templates(self) -> None:
        base, _ = self._base_recipe()
        if base is None:
            self._other_template.set_options([], keep_value=False)
            return
        keep = self._other_template.value
        options = _template_options(base)
        self._other_template.set_options(options, keep_value=False)
        values = [v for _, v in options]
        self._other_template.value = keep if keep in values else base.template_key

    @property
    def experiment_type(self) -> Optional[ExperimentType]:
        """The chosen experiment type (`None` for 'Other' or no choice)."""
        return EXPERIMENT_TYPES.get(self._type_table.value or "")

    # 4 Details

    def _fill_step_types(self) -> None:
        """Offer the fixed step's experiment types; preselect by the channel's detector."""
        if self._fixed_step is None:
            return
        types = list(CHAIN_BY_ID[self._fixed_step].experiment_types)
        channel = self._channel.value
        if not self._type_chosen and channel != self._typed_for_channel:
            self._typed_for_channel = channel
            hint = _detector_hint(channel or "")
            matches = [t for t in types if EXPERIMENT_TYPES[t].detector == hint]
            if self._explicit_type in types:
                choice = self._explicit_type
            else:
                choice = matches[0] if len(matches) == 1 else (self._default_type or types[0])
            self._type_table.value = choice
        was_loading = self._loading
        self._loading = True
        try:
            self._step_type.options = [(EXPERIMENT_TYPES[t].label, t) for t in types]
            self._step_type.value = self._type_table.value
        finally:
            self._loading = was_loading
        self._step_type.layout.display = "" if len(types) > 1 else "none"
        self._show_step_type()

    def _show_step_type(self) -> None:
        types = CHAIN_BY_ID[self._fixed_step].experiment_types if self._fixed_step else ()
        if len(types) == 1:
            experiment_type = EXPERIMENT_TYPES[types[0]]
            self._step_type_info.value = (
                f"<p><b>Experiment:</b> {html.escape(experiment_type.label)} — what you run: "
                f"{html.escape(experiment_type.what_you_run)}</p>"
            )
            return
        lines = "".join(
            f"<li><b>{html.escape(EXPERIMENT_TYPES[t].label)}</b>: "
            f"{html.escape(EXPERIMENT_TYPES[t].what_you_run)}</li>"
            for t in types
        )
        self._step_type_info.value = (
            "<p><b>Which experiment did you run?</b> Preselected from the channel's "
            f"detector where it tells them apart.</p><ul class='cadetgui-note'>{lines}</ul>"
        )

    def _on_step_type(self, change: dict) -> None:
        if self._loading or change["new"] is None:
            return
        self._type_chosen = True
        self._type_table.value = change["new"]
        if self.page == 3:
            self._prefill_details()

    def _check_name(self, name: str) -> Optional[str]:
        if not name.strip():
            return "A name is required."
        if any(c.name == name.strip() for c in self.study.comparisons):
            return f"{name!r} is already used."
        return None

    def _check_new_component(self, name: str) -> Optional[str]:
        if self._component.value != _NEW:
            return None
        name = name.strip()
        if not name:
            return "Name the new component (the injected substance)."
        if name == SALT:
            return f"{SALT!r} is reserved for the salt component."
        existing = self.study.component(name)
        if existing is None:
            return None
        experiment_type = self.experiment_type
        if experiment_type is not None and existing.role not in experiment_type.probe_roles:
            return (
                f"{name!r} is already declared as {existing.role}; see below how to use it, "
                "or give the new component another name."
            )
        return f"{name!r} is already declared as {existing.role}; pick it from the list."

    def _fill_components(self, prefer: Optional[str]) -> None:
        """Offer the declared components whose role fits the chosen type, plus a new one."""
        experiment_type = self.experiment_type
        roles = experiment_type.probe_roles if experiment_type is not None else tuple(
            r for r in COMPONENT_ROLES if r != SALT_ROLE
        )
        fitting = [c for c in self.study.components if c.role in roles]
        options: List[Tuple[str, Optional[str]]] = []
        if experiment_type is None:
            options.append(("None", None))
        options += component_options(self.study, roles)
        options.append(("New component…", _NEW))
        names = [c.name for c in fitting]
        value = prefer if prefer in names else (names[0] if names else _NEW)
        if experiment_type is None and prefer is None:
            value = None
        self._component.set_options(options, keep_value=False)
        self._component.value = value
        self._new_role.set_options([(r, r) for r in roles], keep_value=False)
        self._new_component.value = ""
        if experiment_type is not None and not fitting:
            wanted = html.escape(" or ".join(roles))
            label = html.escape(experiment_type.label)
            self._component_note.value = (
                f"No declared component is a {wanted}; {label} needs one. Name it below; "
                "it is added to System → Components."
            )
            if len(options) > 1:
                self._component_note.value += (
                    " Or pick a declared component marked \"not a …\" and change its role."
                )
        else:
            self._component_note.value = (
                "The " + term_html("component") + " links this measurement's fitted values "
                "to the other steps; pick the same one wherever the same molecule is injected."
            )
        self._sync_new_component()

    def _sync_new_component(self) -> None:
        new = self._component.value == _NEW
        self._new_component.layout.display = "" if new else "none"
        self._new_role.layout.display = "" if new else "none"
        self._new_component._run_validate()
        self._refresh_role_fix()

    def _component_role_fix(self) -> Tuple[str, Optional[str]]:
        """Return `role_fix` for the picked (or typed, already declared) component."""
        experiment_type, name = self.experiment_type, self.component
        if experiment_type is None or not name:
            return "", None
        return role_fix(self.study, name, experiment_type)

    def _refresh_role_fix(self) -> None:
        text, target = self._component_role_fix()
        name = self.component
        self._role_fix_target = (name, target) if target is not None and name else None
        self._role_fix.value = status_html("warn", text) if text else ""
        if self._role_fix_target is not None:
            self._btn_role_fix.description = f"Make {name} a {target}"
        self._btn_role_fix.layout.display = "" if self._role_fix_target else "none"

    def make_component_fit(self) -> None:
        """Give the picked component the role this experiment needs, then select it."""
        if self._role_fix_target is None:
            return
        name, role = self._role_fix_target
        self.study.set_component_role(name, role)
        self._fill_components(name)
        self.status.value = status_html("ok", f"{name} is now a {role}.")

    @property
    def component(self) -> Optional[str]:
        """The chosen component's name (the new one's when "New component…" is picked)."""
        value = self._component.value
        return self._new_component.value.strip() or None if value == _NEW else value

    def new_component(self, name: str, role: Optional[str] = None) -> None:
        """Pick "New component…" with `name` (and `role`, else the type's first role)."""
        self._component.value = _NEW
        self._new_component.value = name
        if role is not None:
            self._new_role.value = role

    def _unique_name(self, base: str) -> str:
        names = {c.name for c in self.study.comparisons}
        if base not in names:
            return base
        i = 2
        while f"{base} {i}" in names:
            i += 1
        return f"{base} {i}"

    def _prefill_details(self) -> None:
        experiment_type = self.experiment_type
        base, _ = self._base_recipe()
        key = (self._type_table.value, self.data_file, self._channel.value, id(base))
        if key != self._prefilled_for:
            self._prefilled_for = key
            label = self.run.label if self.run is not None else "Measurement"
            self._name.value = self._unique_name(label)
            probes = [
                c.probe for c in self.study.comparisons
                if c.probe and experiment_type is not None
                and c.experiment_type == experiment_type.id
            ]
            self._fill_components(probes[0] if probes else None)
            flow_rate = None
            if base is not None:
                recipe = (
                    experiment_type.apply(base, component="Probe")
                    if experiment_type is not None else base
                )
                flow_rate = _recipe_flow_rate(recipe)
            self._flow_rate.value = _format(
                flow_rate / _ML_PER_MIN if flow_rate is not None else None
            )
            self._fill_markers(experiment_type)
        self._new_component._run_validate()
        self._details_note.value = (
            "The flow rate is prefilled from the recipe; change it if this run used "
            "another one. The " + term_html("injection marker") + " was picked from the run "
            "log by the experiment type's keywords; change it if it is wrong."
        )

    def _fill_markers(self, experiment_type: Optional[ExperimentType]) -> None:
        run = self.run
        options: List[Tuple[str, Optional[str]]] = [("None / manual", None)]
        options += [
            (f"{text} (at {x:g} {run.x_unit} in the run log)", text) for x, text in run.markers
        ]
        keywords = experiment_type.marker_keywords if experiment_type is not None else (
            "inject", "sample", "elution"
        )
        self._marker.set_options(options, keep_value=False)
        self._marker.value = find_injection_marker(run, keywords)

    # 5 Confirm

    def draft(self) -> Comparison:
        """Return the comparison the current choices describe; raises without a base recipe."""
        base, _ = self._base_recipe()
        if base is None or self.run is None:
            raise ValueError("A base recipe and a run are needed.")
        name = self._name.value.strip()
        channel = self._channel.value or ""
        marker = self._marker.value
        flow_rate = _optional_float(self._flow_rate.value)
        flow_rate = flow_rate * _ML_PER_MIN if flow_rate is not None else None
        experiment_type = self.experiment_type
        if experiment_type is None:
            recipe = copy.deepcopy(base)
            template = self._other_template.value
            if template is not None and template != base.template_key:
                recipe = recipe_with_template(recipe, template)
            recipe_flow = _recipe_flow_rate(recipe)
            options = list(check_recipe(recipe).signal_options)
            unit, port = options[0][1] if options else ("outlet", "inlet")
            comparison = Comparison(
                name=name,
                data_file=self.data_file,
                channel=channel,
                recipe=recipe,
                solution_path=f"{unit}.{port}",
                flow_rate=None if _same(flow_rate, recipe_flow) else flow_rate,
                injection_marker=marker,
                probe=self.component,
                run=self.run,
            )
            return comparison
        component = self.component or ""
        recipe_flow = experiment_type.apply(base, component=component).model_values.get(
            "flow_rate"
        )
        comparison = measurement_from_run(
            name, self.run, channel, experiment_type, base,
            component=component,
            flow_rate=None if _same(flow_rate, recipe_flow) else flow_rate,
            injection_marker=marker,
        )
        return dataclasses.replace(comparison, data_file=self.data_file, injection_marker=marker)

    def _show_confirm(self) -> None:
        base, source = self._base_recipe()
        self._base_note.value = (
            "<p class='cadetgui-note'>Base " + term_html("recipe") + ": "
            + html.escape(source, quote=False) + ".</p>"
        )
        experiment_type = self.experiment_type
        implied = experiment_type.implied if experiment_type is not None else ()
        self._implied.layout.display = "" if implied else "none"
        self._implied_note.value = (
            "This experiment type assumes: " + "; ".join(
                html.escape(f"{item.path} = {item.value:g} ({item.note})") for item in implied
            ) + ". Nothing is written unless you tick the box."
            if implied else ""
        )
        if base is None:
            self._summary.value = self._diagram.value = ""
            self._confirm_problems.value = status_html(
                "error", "No base recipe: build a process in Process Configuration first."
            )
            self._btn_add.disabled = True
            return
        comparison = self.draft()
        self._summary.value = recipe_summary_html(comparison)
        self._diagram.value = recipe_diagram_svg(
            comparison.recipe, observe=_observed_unit(comparison.solution_path), compact=True
        )
        self._confirm_problems.value = problems_html(comparison.problems())
        self._btn_add.disabled = False

    def confirm(self) -> Optional[Comparison]:
        """Add the drafted comparison to the study (and implied values if ticked)."""
        for page in self._visible_pages[:-1]:
            self.page = page
            error = self._page_error()
            if error:
                self._go(page)
                self.status.value = status_html("error", error)
                return None
        self.page = len(_PAGES) - 1
        base, _ = self._base_recipe()
        if base is None:
            self.status.value = status_html(
                "error", "No base recipe: build a process in Process Configuration first."
            )
            return None
        comparison = self.draft()
        notes: List[str] = []
        if self._component.value == _NEW and comparison.probe:
            self.study.add_component(comparison.probe, self._new_role.value)
            notes.append(
                f"Declared {comparison.probe} ({self._new_role.value}) under System → "
                "Components."
            )
        self.study.upsert_comparison(comparison)
        experiment_type = self.experiment_type
        if experiment_type is not None and experiment_type.implied and self._implied.value:
            self.study.initial_store = with_implied_values(
                self.study.initial_store, experiment_type, comparison.probe
            )
            self.study.notify()
            notes.append(
                "Added to the parameter store (assumed by the experiment type): "
                + ", ".join(f"{i.path} = {i.value:g}" for i in experiment_type.implied) + "."
            )
        self.close()
        self._on_added(comparison, notes)
        return comparison
