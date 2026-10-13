from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

import ipywidgets as W
from CADETProcess.processModel import ComponentSystem

from ...instrument.system import BINDING_MODELS, COLUMN_MODELS
from ...parameters.specs import MULTIPLEXABLE_COLUMN_PARAMS, build_parameter_config_spec
from ..elements import ChoiceField
from ..forms import FormRenderer
from ..ui.layout import SettingsPopover, note, section, titled_header

__all__ = ["ColumnBindingSection"]


_BYPASS_NOTE = "Column is bypassed in the System configuration -- these settings are not used."


def _checkbox(description: str, on_change: Callable[[dict], None]) -> W.Checkbox:
    box = W.Checkbox(description=description, value=False, indent=False)
    box.observe(on_change, names="value")
    return box


class ColumnBindingSection:
    """The column and binding model pickers, their parameter forms and display settings.

    `on_selection_change` fires when a picker changes, `on_settings_change` when a
    form-shaping setting does, and `on_reset` with "column" or "binding" on that form's Reset.
    """

    def __init__(
        self,
        *,
        on_selection_change: Callable[[], None],
        on_settings_change: Callable[[], None],
        on_reset: Callable[[str], None],
    ) -> None:
        self._on_settings_change = on_settings_change
        self._on_reset = on_reset
        self.column_form: Optional[FormRenderer] = None
        self.binding_form: Optional[FormRenderer] = None
        self._forms_key: Optional[tuple] = None
        self._column_cache: dict[Any, Any] = {}
        self._binding_cache: dict[Any, Any] = {}

        self.multiplex_state: dict[str, bool] = dict.fromkeys(MULTIPLEXABLE_COLUMN_PARAMS, False)
        self.multiplex_checkboxes: dict[str, W.Checkbox] = {
            name: _checkbox(
                f"Enable {name.replace('_', ' ').title()} Multiplex",
                self._make_on_multiplex_change(name),
            )
            for name in MULTIPLEXABLE_COLUMN_PARAMS
        }
        self.show_optional_column = _checkbox(
            "Show optional parameters", lambda _c: on_settings_change()
        )
        column_settings = SettingsPopover(
            tooltip="Column settings",
            children=[self.show_optional_column, *self.multiplex_checkboxes.values()],
        )
        self.show_optional_binding = _checkbox(
            "Show optional parameters", lambda _c: on_settings_change()
        )
        binding_settings = SettingsPopover(
            tooltip="Binding settings", children=[self.show_optional_binding]
        )

        self.column_bypass_note = note(_BYPASS_NOTE, hidden=True)
        self.binding_bypass_note = note(_BYPASS_NOTE, hidden=True)
        self.column_picker = ChoiceField(
            label="Column Model:",
            options=list(COLUMN_MODELS.items()),
            value=COLUMN_MODELS.get("Lumped Rate Model Without Pores (LRM)"),
        )
        self.binding_picker = ChoiceField(
            label="Binding Model:",
            options=list(BINDING_MODELS.items()),
            value=BINDING_MODELS.get("Linear"),
        )
        self.column_form_box = W.VBox([])
        self.binding_form_box = W.VBox([])

        column_section = section(
            [
                titled_header("Column Model", column_settings.button),
                column_settings.box,
                self.column_bypass_note,
                self.column_picker,
                self.column_form_box,
            ],
            "cadetgui-section-half",
        )
        binding_section = section(
            [
                titled_header("Binding Model", binding_settings.button),
                binding_settings.box,
                self.binding_bypass_note,
                self.binding_picker,
                self.binding_form_box,
            ],
            "cadetgui-section-half",
        )
        self.root = W.HBox([column_section, binding_section])
        self.root.add_class("cadetgui-row")

        self.column_picker.observe(lambda _c: on_selection_change(), names="selected_index")
        self.binding_picker.observe(lambda _c: on_selection_change(), names="selected_index")

    def _make_on_multiplex_change(self, name: str) -> Callable[[dict], None]:
        def _on_change(change: dict) -> None:
            self.multiplex_state[name] = bool(change["new"])
            self._on_settings_change()

        return _on_change

    def restore_settings(
        self, multiplex_state: dict[str, bool], show_optional_column: bool,
        show_optional_binding: bool,
    ) -> None:
        """Set the multiplex and show-optional settings from a saved state."""
        for param_name, enabled in multiplex_state.items():
            box = self.multiplex_checkboxes.get(param_name)
            if box is not None:
                box.value = enabled
        self.show_optional_column.value = show_optional_column
        self.show_optional_binding.value = show_optional_binding

    def clear_cache(self) -> None:
        """Forget the detached column and binding model instances."""
        self._column_cache.clear()
        self._binding_cache.clear()

    def detached_column(self, components: Sequence[str]) -> Any:
        """Return a cached column of the picked class over `components`, or None."""
        column_cls = self.column_picker.value
        if column_cls is None:
            return None
        cache_key = (column_cls, tuple(components))
        if cache_key not in self._column_cache:
            cs = ComponentSystem(list(components))
            self._column_cache[cache_key] = column_cls(cs, name="column")
        return self._column_cache[cache_key]

    def detached_binding_model(self, column: Any) -> Any:
        """Return a cached binding model of the picked class for `column`, or None."""
        binding_cls = self.binding_picker.value
        if binding_cls is None:
            return None
        # A binding model must share its column's component system, so it is keyed per column.
        cache_key = (binding_cls, id(column))
        if cache_key not in self._binding_cache:
            self._binding_cache[cache_key] = binding_cls(
                column.component_system, name="binding_model"
            )
        return self._binding_cache[cache_key]

    def set_bypassed(self, off: bool) -> None:
        """Grey out the pickers, settings and forms while the column is bypassed."""
        for control in (
            self.column_picker,
            self.binding_picker,
            self.show_optional_column,
            self.show_optional_binding,
            *self.multiplex_checkboxes.values(),
        ):
            control.disabled = off
        for form in (self.column_form, self.binding_form):
            if form is not None:
                form.set_disabled(off)
        display = "" if off else "none"
        self.column_bypass_note.layout.display = display
        self.binding_bypass_note.layout.display = display

    def clear(self) -> None:
        """Remove the forms from view."""
        self.column_form_box.children = ()
        self.binding_form_box.children = ()

    def rebuild(
        self, column: Any, binding_model: Any, components: Sequence[str], *, carry: bool
    ) -> None:
        """Build fresh forms; with `carry`, keep the previous values if their shape is unchanged."""
        form_key = (
            self.column_picker.value,
            self.binding_picker.value,
            tuple(components),
            tuple(sorted(self.multiplex_state.items())),
            bool(self.show_optional_column.value),
            bool(self.show_optional_binding.value),
        )
        carry = carry and form_key == self._forms_key
        previous_column = self.column_form.collect_values() if carry and self.column_form else None
        previous_binding = (
            self.binding_form.collect_values() if carry and self.binding_form else None
        )
        self._forms_key = form_key
        self._rebuild_column_form(column, previous_column)
        self._rebuild_binding_form(column, binding_model, previous_binding)

    def _rebuild_column_form(self, column: Any, previous: Optional[dict]) -> None:
        if column is None:
            self.column_form = None
            self.column_form_box.children = ()
            return
        applicable = set(getattr(column, "required_parameters", None) or []) & (
            MULTIPLEXABLE_COLUMN_PARAMS
        )
        for name, box in self.multiplex_checkboxes.items():
            box.layout.display = "" if name in applicable else "none"
        self.column_form = FormRenderer(
            build_parameter_config_spec(
                column,
                multiplex=self.multiplex_state,
                include_optional=self.show_optional_column.value,
            ),
            on_reset=lambda: self._on_reset("column"),
        )
        self.column_form_box.children = (self.column_form.root,)
        if previous is not None:
            self.column_form.set_values(previous)

    def _rebuild_binding_form(
        self, column: Any, binding_model: Any, previous: Optional[dict]
    ) -> None:
        if binding_model is None:
            self.binding_form = None
            self.binding_form_box.children = ()
            return

        def _attach_binding(built: Any) -> None:
            column.binding_model = built

        self.binding_form = FormRenderer(
            build_parameter_config_spec(
                binding_model, include_optional=self.show_optional_binding.value
            ),
            on_built=_attach_binding,
            on_reset=lambda: self._on_reset("binding"),
        )
        self.binding_form_box.children = (self.binding_form.root,)
        if previous is not None:
            self.binding_form.set_values(previous)
