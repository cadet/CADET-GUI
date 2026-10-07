from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

import ipywidgets as W

from ...characterization_guide import COMPONENT_ROLES, SALT, SALT_ROLE
from ...study import Study
from .._chrome import style_tag
from .._help import info_box_html, term_html
from .._status import status_html

__all__ = ["StudyComponentsWidget", "COMPONENTS_HELP"]

COMPONENTS_HELP = (
    "<p>Components are the molecules you inject or elute with: tracers, the protein and, "
    "for gradient and breakthrough runs, the salt. Each measurement picks its component "
    "from this list, and the experiment type decides which "
    + term_html("component role", "roles") + " fit.</p>"
    "<p>Fitted values are stored under the component's name, so the name links values "
    "across steps: the protein's film diffusion from Particle transport is reused in "
    "Binding only if both measurements use the same component. Values measured with a "
    "tracer reach another molecule only through an explicit "
    + term_html("species transfer") + ".</p>"
)

_ROLE_OPTIONS = [(role, role) for role in COMPONENT_ROLES]
SALT_NAME_NOTE = "fixed name, required by the binding model"


def _role_dropdown(**kwargs: Any) -> W.Dropdown:
    dropdown = W.Dropdown(**kwargs)
    dropdown.add_class("cadetgui-select")
    return dropdown


class StudyComponentsWidget:
    """Editor over `study.components`: one row per component (name, role), add and remove.

    Renames, role changes and removals go through the `Study` methods, which refuse what
    would break a measurement or detach stored values; the refusal is shown in `.status`.
    The salt component's name is fixed to `SALT`: its row is read-only, and picking the
    salt role in the add row fills in and locks that name.
    """

    def __init__(self, study: Study) -> None:
        self.study = study
        self.rows: Dict[str, Tuple[W.Text, W.Dropdown, W.Button]] = {}
        self._key: Any = None
        self._syncing = False

        self._rows_box = W.VBox()
        self._new_name = W.Text(placeholder="e.g. IgG", description="New:",
                                continuous_update=False)
        self._new_role = _role_dropdown(options=_ROLE_OPTIONS, value="protein",
                                        description="Role:")
        self._btn_add = W.Button(description="Add component", icon="plus")
        self._btn_add.on_click(lambda _b: self.add(self._new_name.value, self._new_role.value))
        self._role_help = W.HTML()
        self._new_role.observe(lambda _c: self._sync_new_role(), names="value")
        self.status = W.HTML()
        self.status.add_class("cadetgui-status")

        add_row = W.HBox([self._new_name, self._new_role, self._btn_add],
                         layout=W.Layout(flex_flow="row wrap"))
        add_row.add_class("cadetgui-toolbar")
        self.root = W.VBox([
            W.HTML(style_tag()),
            W.HTML("<div class='cadetgui-section-title'>"
                   + term_html("component", "Components") + "</div>"),
            W.HTML(info_box_html("What goes here?", COMPONENTS_HELP)),
            self._rows_box,
            add_row,
            self._role_help,
            self.status,
        ])
        self.root.add_class("cadetgui-section")

        self._show_role_help()
        self.refresh()
        study.add_listener(self.refresh)

    def _sync_new_role(self) -> None:
        salt = self._new_role.value == SALT_ROLE
        if salt:
            self._new_name.value = SALT
        elif self._new_name.disabled:
            self._new_name.value = ""
        self._new_name.disabled = salt
        self._show_role_help()

    def _show_role_help(self) -> None:
        role = self._new_role.value
        text = f"{role}: {COMPONENT_ROLES[role]}"
        if role == SALT_ROLE:
            text += f" The name is set to {SALT} ({SALT_NAME_NOTE})."
        elif self.study.component(SALT) is not None:
            text += f" The salt role is not offered: {SALT} is already declared."
        self._role_help.value = f"<small class='cadetgui-note'>{text}</small>"

    def _refresh_new_role_options(self) -> None:
        has_salt = self.study.component(SALT) is not None
        options = [o for o in _ROLE_OPTIONS if not (has_salt and o[1] == SALT_ROLE)]
        if list(self._new_role.options) != options:
            if has_salt and self._new_role.value == SALT_ROLE:
                self._new_role.value = "protein"
            self._new_role.options = options
        self._show_role_help()

    def refresh(self) -> None:
        """Rebuild the rows when the declared components or their use changed."""
        usage = [(c.name, c.role, len(self.study.measurements_using(c.name)))
                 for c in self.study.components]
        self._refresh_new_role_options()
        if usage == self._key:
            return
        self._key = usage
        self.rows = {}
        children: List[W.Widget] = []
        for name, role, used in usage:
            text = W.Text(value=name, continuous_update=False, layout=W.Layout(width="200px"))
            dropdown = _role_dropdown(options=_ROLE_OPTIONS, value=role,
                                      layout=W.Layout(width="160px"))
            remove = W.Button(icon="trash", tooltip=f"Remove {name}",
                              layout=W.Layout(width="40px"), disabled=bool(used))
            if role == SALT_ROLE:
                text.disabled = dropdown.disabled = True
            text.observe(self._on_rename(name), names="value")
            dropdown.observe(self._on_role(name), names="value")
            remove.on_click(lambda _b, name=name: self.remove(name))
            fixed = f"{SALT_NAME_NOTE} · " if role == SALT_ROLE else ""
            note = W.HTML(
                f"<small>{fixed}{term_html(role, 'about this role')} · used by {used} "
                f"measurement{'s' * (used != 1)}</small>",
            )
            self.rows[name] = (text, dropdown, remove)
            row = W.HBox([text, dropdown, remove, note],
                         layout=W.Layout(align_items="center", flex_flow="row wrap"))
            children.append(row)
        if not children:
            children.append(W.HTML(
                "<em>No components yet. Add the tracers and the protein you inject.</em>"
            ))
        self._rows_box.children = children

    def _on_rename(self, old: str) -> Callable[[dict], None]:
        def _handler(change: dict) -> None:
            if not self._syncing:
                self.rename(old, change["new"])
        return _handler

    def _on_role(self, name: str) -> Callable[[dict], None]:
        def _handler(change: dict) -> None:
            if not self._syncing:
                self.set_role(name, change["new"])
        return _handler

    def _run(self, action: Callable[[], Any], ok: str) -> bool:
        try:
            action()
        except (KeyError, ValueError) as exc:
            self.status.value = status_html("error", str(exc.args[0]))
            self._key = None
            self._syncing = True
            try:
                self.refresh()
            finally:
                self._syncing = False
            return False
        self.status.value = status_html("ok", ok)
        return True

    def add(self, name: str, role: str) -> bool:
        """Declare a component; returns whether it was added."""
        name = name.strip()
        if self._run(lambda: self.study.add_component(name, role), f"Added {name} ({role})."):
            self._new_name.value = ""
            return True
        return False

    def rename(self, old: str, new: str) -> bool:
        """Rename a component everywhere it is used; returns whether it was renamed."""
        new = new.strip()
        return self._run(lambda: self.study.rename_component(old, new),
                         f"Renamed {old} to {new} in the measurements using it.")

    def set_role(self, name: str, role: str) -> bool:
        """Change a component's role; returns whether it changed."""
        def action() -> None:
            if role == SALT_ROLE and name != SALT:
                where = (
                    f"{SALT} is already declared" if self.study.component(SALT) is not None
                    else f"add {SALT} with the salt role in the row below instead"
                )
                raise ValueError(
                    f"{name} cannot take the salt role: only the component named {SALT} "
                    f"can ({SALT_NAME_NOTE}); {where}."
                )
            self.study.set_component_role(name, role)
        return self._run(action, f"{name} is now {role}.")

    def remove(self, name: str) -> bool:
        """Remove an unused component; returns whether it was removed."""
        return self._run(lambda: self.study.remove_component(name), f"Removed {name}.")

    def display(self) -> None:
        """Render this widget in a Jupyter cell."""
        from IPython.display import display as _display

        _display(self.root)
