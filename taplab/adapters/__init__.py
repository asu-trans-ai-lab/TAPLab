"""TAPAdapters registry. Each adapter exposes
solve(instance, algorithm, gap, max_time) -> {flows, convergence, summary}."""
from __future__ import annotations

from . import reference_fw


def get(name: str):
    if name == "reference_fw":
        return reference_fw
    if name == "taplite":
        from . import taplite
        return taplite
    if name == "tapb":
        from . import tapb
        return tapb
    if name == "aequilibrae":
        from . import aequilibrae_adapter
        return aequilibrae_adapter
    raise KeyError(f"unknown adapter: {name}")


AVAILABLE = ["reference_fw", "taplite", "tapb", "aequilibrae"]
