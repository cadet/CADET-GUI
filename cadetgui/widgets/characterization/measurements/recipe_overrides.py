"""Process template, recipe source and per-measurement method overrides of a measurement."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import ipywidgets as W

from ....instrument.recipes import recipe_template_fields, template_options
from ....io import configuration_store
from ....io.configuration_store import ConfigurationState
from ....parameters.specs import FieldSpec, parse_float_list
from ...elements import ChoiceField, TextField
from ...ui.layout import note
from .labels import check_float, check_float_list, number_or_blank, value_text

__all__ = ["CURRENT_CONFIGURATION", "RecipeOverrides"]

CURRENT_CONFIGURATION = "__configuration__"


class RecipeOverrides:
    """Template choice, where to take the recipe from, and one field per template value.

    `on_edit` is called when an override field changes; the host observes `template`
    and `use_recipe` itself.
    """

    def __init__(self, on_edit: Callable[..., None]) -> None:
        self._on_edit = on_edit
        self.fields: Dict[str, Tuple[FieldSpec, Any]] = {}
        self.template = ChoiceField(label="Process template:")
        self.template_note = note(
            "Changing the process template changes this measurement's method: its timing "
            "and concentrations go back to the new template's defaults (the flow rate is "
            "kept). Experiment types set their template for you; change it only if the run "
            "followed another method."
        )
        self.source = ChoiceField(label="Recipe from:")
        self.use_recipe = W.Button(description="Use recipe", icon="download")
        self.box = W.HBox(layout=W.Layout(flex_flow="row wrap"))

    def fill_sources(self, *, with_configuration: bool, store_dir: Optional[str]) -> None:
        """Offer the measurement's own recipe, the configuration's and the saved ones."""
        options: List[Tuple[str, Any]] = [("Keep this measurement's recipe", None)]
        if with_configuration:
            options.append(("Current configuration", CURRENT_CONFIGURATION))
        options.extend(
            (f"Saved: {name} ({hash_[:8]})", hash_)
            for name, hash_ in configuration_store.list_store(store_dir=store_dir)
        )
        self.source.set_options(options, keep_value=False)

    def load(self, recipe: ConfigurationState, overrides: dict) -> None:
        """Show `recipe`'s template and one field per template value, holding `overrides`."""
        self.template.set_options(template_options(recipe), keep_value=False)
        self.template.value = recipe.template_key
        self.fields.clear()
        children = [note("Overrides (blank = recipe value)")]
        for spec in recipe_template_fields(recipe):
            current = overrides.get(spec.name)
            recipe_value = recipe.model_values.get(spec.name, spec.default)
            label = f"{spec.label or spec.name} [recipe {value_text(recipe_value)}]:"
            if spec.kind == "choice":
                element: Any = ChoiceField(
                    label=label,
                    options=[(f"recipe ({recipe_value})", None), *(spec.options or ())],
                    value=current,
                )
                element.observe(self._on_edit, names="selected_index")
            else:
                shown = (
                    ", ".join(f"{v:g}" for v in current) if spec.kind == "float_list" and current
                    else number_or_blank(current)
                )
                element = TextField(
                    label=label,
                    value=shown,
                    units=spec.units,
                    validate=check_float_list if spec.kind == "float_list" else check_float,
                )
                element.observe(self._on_edit, names="value")
            self.fields[spec.name] = (spec, element)
            children.append(element)
        self.box.children = children

    def read(self) -> dict:
        """Return the overrides the fields hold (blank fields are left out)."""
        overrides = {}
        for name, (spec, element) in self.fields.items():
            if spec.kind == "choice":
                if element.value is not None:
                    overrides[name] = element.value
            elif element.value.strip():
                overrides[name] = (
                    parse_float_list(element.value) if spec.kind == "float_list"
                    else float(element.value)
                )
        return overrides

    def elements(self) -> List[Any]:
        """Return the override fields."""
        return [element for _, element in self.fields.values()]
