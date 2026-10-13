"""Pick the injected component of a new measurement, or name a new one."""

from __future__ import annotations

import html
from typing import Callable, List, Optional, Tuple

from ....characterization.guide import (
    COMPONENT_ROLES,
    SALT,
    SALT_ROLE,
    ExperimentType,
    role_fix,
)
from ....characterization.study import Study
from ...elements import ChoiceField, TextField
from ...ui.layout import note
from ..help import term_html
from .labels import component_options
from .role_fix import RoleFixPrompt

__all__ = ["ComponentPicker", "NEW"]

NEW = "__new__"


class ComponentPicker:
    """Declared components fitting the experiment type, "New component…", and role fixes."""

    def __init__(
        self, study: Study, experiment_type: Callable[[], Optional[ExperimentType]]
    ) -> None:
        self.study = study
        self._experiment_type = experiment_type
        self.choice = ChoiceField(label="Component:")
        self.new_name = TextField(label="New component:", validate=self._check_new_name)
        self.new_role = ChoiceField(label="Role:")
        self.note = note()
        self.role_fix = RoleFixPrompt()
        self.choice.observe(lambda _c: self.sync_new(), names="selected_index")
        self.new_name.observe(lambda _c: self.refresh_role_fix(), names="value")

    @property
    def is_new(self) -> bool:
        """Whether "New component…" is picked."""
        return self.choice.value == NEW

    @property
    def value(self) -> Optional[str]:
        """The picked component's name (the new one's when "New component…" is picked)."""
        value = self.choice.value
        return self.new_name.value.strip() or None if value == NEW else value

    def set_new(self, name: str, role: Optional[str] = None) -> None:
        """Pick "New component…" with `name` (and `role`, else the type's first role)."""
        self.choice.value = NEW
        self.new_name.value = name
        if role is not None:
            self.new_role.value = role

    def fill(self, prefer: Optional[str]) -> None:
        """Offer the declared components whose role fits the experiment type, plus a new one."""
        experiment_type = self._experiment_type()
        roles = experiment_type.probe_roles if experiment_type is not None else tuple(
            r for r in COMPONENT_ROLES if r != SALT_ROLE
        )
        fitting = [c for c in self.study.components if c.role in roles]
        options: List[Tuple[str, Optional[str]]] = []
        if experiment_type is None:
            options.append(("None", None))
        options += component_options(self.study, roles)
        options.append(("New component…", NEW))
        names = [c.name for c in fitting]
        value = prefer if prefer in names else (names[0] if names else NEW)
        if experiment_type is None and prefer is None:
            value = None
        self.choice.set_options(options, keep_value=False)
        self.choice.value = value
        self.new_role.set_options([(r, r) for r in roles], keep_value=False)
        self.new_name.value = ""
        if experiment_type is not None and not fitting:
            wanted = html.escape(" or ".join(roles))
            label = html.escape(experiment_type.label)
            self.note.value = (
                f"No declared component is a {wanted}; {label} needs one. Name it below; "
                "it is added to System → Components."
            )
            if len(options) > 1:
                self.note.value += (
                    " Or pick a declared component marked \"not a …\" and change its role."
                )
        else:
            self.note.value = (
                "The " + term_html("component") + " links this measurement's fitted values "
                "to the other steps; pick the same one wherever the same molecule is injected."
            )
        self.sync_new()

    def sync_new(self) -> None:
        """Show the new-component fields only while "New component…" is picked."""
        new = self.is_new
        self.new_name.layout.display = "" if new else "none"
        self.new_role.layout.display = "" if new else "none"
        self.new_name._run_validate()
        self.refresh_role_fix()

    def role_fix_text(self) -> Tuple[str, Optional[str]]:
        """Return `role_fix` for the picked (or typed, already declared) component."""
        experiment_type, name = self._experiment_type(), self.value
        if experiment_type is None or not name:
            return "", None
        return role_fix(self.study, name, experiment_type)

    def refresh_role_fix(self) -> None:
        """Show whether the picked component's role fits, with the fix if there is one."""
        text, target = self.role_fix_text()
        self.role_fix.show(self.value, text, target)

    def _check_new_name(self, name: str) -> Optional[str]:
        if not self.is_new:
            return None
        name = name.strip()
        if not name:
            return "Name the new component (the injected substance)."
        if name == SALT:
            return f"{SALT!r} is reserved for the salt component."
        existing = self.study.component(name)
        if existing is None:
            return None
        experiment_type = self._experiment_type()
        if experiment_type is not None and existing.role not in experiment_type.probe_roles:
            return (
                f"{name!r} is already declared as {existing.role}; see below how to use it, "
                "or give the new component another name."
            )
        return f"{name!r} is already declared as {existing.role}; pick it from the list."
