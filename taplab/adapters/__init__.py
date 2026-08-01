"""TAPAdapters registry. Each adapter exposes
solve(instance, algorithm, gap, max_time) -> {flows, convergence, summary}."""
from __future__ import annotations

from . import latent_gp, reference_fw


def get(name: str):
    if name == "reference_fw":
        return reference_fw
    if name == "latent_gp":
        return latent_gp
    if name == "taplite":
        from . import taplite
        return taplite
    if name == "tapb":
        from . import tapb
        return tapb
    if name == "aequilibrae":
        from . import aequilibrae_adapter
        return aequilibrae_adapter
    if name == "task":
        from . import task_adapter
        return task_adapter
    raise KeyError(f"unknown adapter: {name}")


AVAILABLE = ["reference_fw", "latent_gp", "taplite", "tapb", "aequilibrae",
             "task"]
