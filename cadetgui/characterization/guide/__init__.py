"""Lab-language guide to the characterization chain: experiment types, default chain, glossary.

An `ExperimentType` says what a lab run implies for the model: which units are in the
flow path, which process template, which component, where the detector sits, which
chain step it feeds and which values it fixes by assumption. `DEFAULT_CHAIN` is the
recommended order of steps with plain-language docs per step. Headless (no ipywidgets).
"""

from .chain import (
    CHAIN_BY_ID,
    DEFAULT_CHAIN,
    ChainStepGuide,
    Determined,
    guide_for_step,
    guide_measurements,
    new_step_setup,
    step_title,
)
from .experiments import (
    EXPERIMENT_TYPES,
    ExperimentType,
    ImpliedValue,
    find_injection_marker,
    map_species,
    measurement_from_run,
    missing_assumptions,
    record_assumptions,
    with_implied_values,
)
from .glossary import GLOSSARY, GLOSSARY_ALIASES, WORKFLOW_GUIDE
from .labels import (
    STEP_TYPE_HELP,
    option_help,
    option_label,
    parameter_label,
    role_fix,
    species_gap_messages,
    step_summary,
    step_type_help,
)
from .roles import (
    COMPONENT_ROLES,
    LARGE_TRACER,
    PROTEIN,
    SALT,
    SALT_ROLE,
    SMALL_TRACER,
    SYSTEM_TRACER,
)
from .start_values import (
    ASSUMED_BY_TYPE,
    FROM_PROCESS,
    STARTING_VALUE,
    StartingValue,
    parameter_unit,
    starting_values,
)

__all__ = [
    "parameter_unit",
    "SALT",
    "COMPONENT_ROLES",
    "SYSTEM_TRACER",
    "SMALL_TRACER",
    "LARGE_TRACER",
    "PROTEIN",
    "SALT_ROLE",
    "Determined",
    "ImpliedValue",
    "ExperimentType",
    "EXPERIMENT_TYPES",
    "ChainStepGuide",
    "DEFAULT_CHAIN",
    "CHAIN_BY_ID",
    "GLOSSARY",
    "GLOSSARY_ALIASES",
    "WORKFLOW_GUIDE",
    "new_step_setup",
    "with_implied_values",
    "missing_assumptions",
    "record_assumptions",
    "measurement_from_run",
    "map_species",
    "find_injection_marker",
    "guide_for_step",
    "parameter_label",
    "step_title",
    "species_gap_messages",
    "guide_measurements",
    "role_fix",
    "option_label",
    "option_help",
    "STEP_TYPE_HELP",
    "step_type_help",
    "step_summary",
    "StartingValue",
    "starting_values",
    "FROM_PROCESS",
    "STARTING_VALUE",
    "ASSUMED_BY_TYPE",
]
