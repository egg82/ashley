"""Eval runners against the live services: `python -m ashley.evals --help`. Each wires the process as the app does
(`ashley.wiring`), which is why they live here and not beside their harnesses: a system's own package may not import
the composition root that imports it."""
