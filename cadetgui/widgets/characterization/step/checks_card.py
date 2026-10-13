"""The "Before you run" checks of a step: one row per check, each open one with its fix."""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Optional

import ipywidgets as W

from ....characterization.step_checks import (
    CONFIRM_KNOWN,
    RECORD_ASSUMPTIONS,
    TRANSFER,
    StepCheck,
)
from ...ui.html import status_html
from ..help import term_html

Navigate = Callable[[str, Dict[str, Any]], None]


class ChecksCard:
    """Rows of live step checks with their fix buttons; rebuilt only when the checks change."""

    def __init__(
        self,
        on_transfer: Callable[[], None],
        on_record_assumptions: Callable[[], None],
        on_confirm_known: Callable[[Any], None],
    ) -> None:
        self._on_record_assumptions = on_record_assumptions
        self._on_confirm_known = on_confirm_known
        self._key: Optional[tuple] = None
        self.known_fields: Dict[str, W.FloatText] = {}
        self.box = W.VBox()
        self.gaps = W.HTML()
        self.btn_transfer = W.Button(
            description="Transfer to this step's species", icon="share",
            layout=W.Layout(display="none", width="auto"),
        )
        self.btn_transfer.on_click(lambda _b: on_transfer())

    def show(
        self, checks: List[StepCheck], *, editable: bool, navigate: Optional[Navigate]
    ) -> None:
        """Show `checks`; local fixes only when `editable`, links elsewhere only with `navigate`."""
        key = (tuple(checks), editable, navigate is not None)
        if key == self._key:
            return
        self._key = key
        gaps = next((c for c in checks if c.id == "species_gaps"), None)
        self.gaps.value = "" if gaps is None else (
            status_html("warn", gaps.text) + " "
            + term_html("species transfer", "(species transfer)")
        )
        self.btn_transfer.layout.display = "" if gaps is not None and editable else "none"
        self.known_fields = {}
        rows = []
        for check in checks:
            if any(action.target == TRANSFER for action in check.actions):
                rows.append(W.HBox(
                    [self.gaps, self.btn_transfer],
                    layout=W.Layout(align_items="center", flex_flow="row wrap"),
                ))
                continue
            controls: List[W.Widget] = [W.HTML(status_html(check.status, check.text))]
            for action in check.actions:
                if action.target == CONFIRM_KNOWN and editable:
                    controls += self._known_value_field(action.context)
                button = self._action_button(action, editable, navigate)
                if button is not None:
                    controls.append(button)
            rows.append(W.HBox(
                controls, layout=W.Layout(align_items="center", flex_flow="row wrap"),
            ))
        self.box.children = rows

    def _known_value_field(self, context: Any) -> List[W.Widget]:
        """Return an editable hardware value prefilled with the default, and its unit."""
        field = W.FloatText(
            value=float(f"{context['value'] / context['scale']:.6g}"),
            tooltip="Your hardware value; the default is prefilled.",
            layout=W.Layout(width="110px"),
        )
        self.known_fields[context["path"]] = field
        return [field, W.HTML(html.escape(context["unit"]))]

    def _action_button(
        self, action: Any, editable: bool, navigate: Optional[Navigate]
    ) -> Optional[W.Button]:
        local = {
            RECORD_ASSUMPTIONS: self._on_record_assumptions,
            CONFIRM_KNOWN: lambda: self._on_confirm_known(action.context),
        }
        if action.target in local:
            if not editable:
                return None
            callback = local[action.target]
        elif navigate is None:
            return None
        else:
            def callback(action: Any = action) -> None:
                navigate(action.target, dict(action.context))
        button = W.Button(description=action.label, layout=W.Layout(width="auto"))
        button.on_click(lambda _b: callback())
        return button

    def entered_value(self, context: Any) -> float:
        """Return the hardware value typed for `context`, or its default."""
        field = self.known_fields.get(context["path"])
        return context["value"] if field is None else field.value * context["scale"]

    def buttons(self) -> Dict[str, W.Button]:
        """Return the buttons of the open checks by label."""
        buttons = {}
        for row in self.box.children:
            for child in row.children:
                if isinstance(child, W.Button) and child.layout.display != "none":
                    buttons[child.description] = child
        return buttons
