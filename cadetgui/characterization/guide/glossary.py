"""Glossary of characterization terms and the step-by-step workflow guide."""

from __future__ import annotations

from typing import Dict

from .roles import COMPONENT_ROLES

GLOSSARY: Dict[str, str] = {
    "measurement": "One recorded run: a data file with one or more detector channels.",
    "characterization step": "One fit of one part of the system (e.g. the extra-column "
    "volume or the column packing) to the measurements that belong to it. Steps run in "
    "chain order; each starts from the values accepted before it.",
    "step type": "What a step fits and how the model represents it, e.g. the length and "
    "dispersion of one tubing segment or the porosities of the column bed. A step of the "
    "recommended chain sets it for you.",
    "extra-column volume": "All the liquid volume a sample passes outside the packed bed "
    "(tubing, valves, mixer, detector cells). It delays and broadens every peak, so it is "
    "characterized first, with a system pulse and no column in line.",
    "comparison": "A measurement paired with the recipe that should reproduce it, the "
    "channel and observation point to compare, and how to align and scale the trace. The "
    "workbench lists each comparison as a measurement.",
    "experiment type": "The kind of lab run (e.g. system pulse, breakthrough); it fixes the "
    "flow path, process template, observation point and which step the run feeds.",
    "recipe": "Everything a fresh simulation of one run is built from: the system (hardware, "
    "flow rate, column and binding model), the components and the method (process "
    "template) of the run's experiment type. It holds no fitted values.",
    "flow path": "The units the liquid passes through in a run; units not used in that run "
    "are bypassed.",
    "observation point": "Where in the flow path the simulated signal is read, matching the "
    "detector's position (e.g. column outlet for UV).",
    "injection marker": "A run-log entry (e.g. 'Phase Elution') marking when the sample was "
    "injected; used to align the measured clock to the simulated one.",
    "alignment": "Shifting the measured trace in time so its injection coincides with the "
    "simulated injection.",
    "baseline window": "A stretch of the run without signal from the probe, used to "
    "estimate and subtract the detector baseline.",
    "normalization": "Scaling the measured trace, e.g. so its peak area equals the injected "
    "amount; removes the unknown detector response factor.",
    "prior": "The parameter values a step starts from: everything accepted before it.",
    "posterior": "The parameter values a step ends with, once a candidate is accepted.",
    "parameter store": "The accepted and known parameter values of the whole chain, each "
    "with its provenance.",
    "provenance": "Where a stored value came from: the step, the probe, the runs, the "
    "metric, or a note if it was assumed.",
    "probe": "The substance injected to measure something (tracer, protein).",
    "component": "A molecule you inject or elute with (tracer, protein, salt), declared "
    "once for the study with its role. Each measurement picks its probe from the declared "
    "components, and fitted values are stored under the component's name, so the same "
    "name links values across steps.",
    "component role": "What a component is in the lab: system tracer, small tracer, large "
    "tracer, protein or salt. The role decides which experiment types may use it.",
    **COMPONENT_ROLES,
    "species transfer": "Explicitly reusing a value measured with one probe for another "
    "(e.g. system dispersion measured with acetone, reused for a protein); recorded as an "
    "assumption.",
    "Pareto candidate": "A fitted parameter set that no other set beats on every "
    "measurement at once.",
    "best average": "The Pareto candidate with the lowest mean error over all measurements.",
    "fitted variable": "A parameter the optimizer searches between a lower and an upper "
    "bound; the value of the candidate you accept is written to the parameter store.",
    "fixed variable": "A parameter a step could fit but is told to keep at its current "
    "value (from an earlier step, the starting parameters or the recipe): its Fit box is "
    "unticked. Use it when the measurements cannot separate two parameters.",
    "NRMSE": "Normalized root-mean-square error between simulated and measured traces; "
    "0 is a perfect match.",
}

GLOSSARY_ALIASES: Dict[str, str] = {"frozen variable": "fixed variable"}
"""Older glossary terms and the entry they resolve to."""

WORKFLOW_GUIDE = """\
# Characterizing a column, step by step

1. **System.** Describe the instrument once: which tubing, mixer and sample loop are
   installed, the known hardware values (tubing diameters, loop volume) and the flow rate
   your runs use; under Advanced configuration, the column and binding model with their
   starting values. This is the base every run starts from. The method (which inlets
   pump, when the loop injects, which units are bypassed) is not part of the system: it
   comes with each measurement's experiment type.
2. **Components.** On the System page, above the hardware, declare the molecules you
   inject or elute with and give each a role (system tracer, small tracer, large tracer,
   protein, salt). Use the same name for the same molecule in every step: fitted values
   are kept per component and reused only under that name. To use a value for another
   molecule (e.g. a tracer's dispersion for your protein), copy it on the step page with
   "Transfer to this step's species" (a species transfer).
3. **Measurements.** Load each run's export. For every run choose its experiment type
   (e.g. "System pulse (no column in line)"), its component and the detector channel;
   the experiment type sets the method (process template), the units the run bypasses
   and the observation point for you.
   Check the injection marker, baseline window and normalization on its measured trace.
4. **Steps, in order.** Work through the chain: Extra-column volume, Column packing,
   Particle transport, Binding, Capacity. For each step, add its measurements first,
   then set the step up from Setup. A step fits one part of the system from its
   measurements; its page lists what it determines and which experiment types feed it.
   Steps run in order, each starting from the values accepted before it, so only start a
   step once the steps before it are accepted.
5. **Before each fit.** Go through the step's "Before you run" checks; each open item
   has a button to fix it, e.g. carrying values measured with one probe over to this
   step's probes (species transfer).
6. **Fit and choose.** Run the fit. Each measurement is one objective; from the Pareto
   candidates pick one, usually "best average", after checking the per-run charts.
7. **Accept.** Accepting writes the chosen values into the parameter store with their
   provenance; the next step starts from there.
8. **Result.** After the last step, the parameter store holds the accepted parameters of
   the whole system, ready to simulate new processes.
"""
