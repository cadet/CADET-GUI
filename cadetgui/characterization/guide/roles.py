"""Component roles of a characterization study and the reserved salt name."""

from __future__ import annotations

from typing import Dict

SALT = "Salt"

SYSTEM_TRACER = "system tracer"
SMALL_TRACER = "small tracer"
LARGE_TRACER = "large tracer"
PROTEIN = "protein"
SALT_ROLE = "salt"

COMPONENT_ROLES: Dict[str, str] = {
    SYSTEM_TRACER: "A non-interacting tracer used only for system pulses (column replaced "
    "by a union). A small tracer such as acetone does both jobs: declare it as a small "
    "tracer instead.",
    SMALL_TRACER: "A small non-binding tracer that enters the bead pores (e.g. acetone or "
    "salt pulse). Also serves as the tracer of system pulses.",
    LARGE_TRACER: "A large non-binding tracer that is excluded from the pores (e.g. "
    "dextran).",
    PROTEIN: "The protein you characterize: non-binding pulses, gradient elution and "
    "breakthrough.",
    SALT_ROLE: "The salt of gradient and breakthrough runs; component 0 of steric mass "
    "action. Its name is fixed to \"" + SALT + "\".",
}
