"""TAPLab Experiment function: perturb demand / capacity (grid) and
re-solve, collecting normalized outcomes for the sensitivity report."""
from __future__ import annotations

import copy
import csv
from pathlib import Path

from . import adapters
from .instance import Instance
from .validate import validate


def _scaled(inst: Instance, ds: float, cs: float) -> Instance:
    out = copy.deepcopy(inst)
    for r in out.demand:
        r["volume"] = str(float(r["volume"]) * ds)
    for r in out.links:
        r["capacity"] = str(float(r["capacity"]) * cs)
    return out


def run_experiment(inst_dir, solver, demand_scales, capacity_scales,
                   gap, max_time, outdir: Path):
    base = Instance.load(inst_dir)
    rep = validate(base)
    if not rep["pass"]:
        raise SystemExit("validation failed: " + "; ".join(rep["errors"]))
    mod = adapters.get(solver)
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for ds in demand_scales:
        for cs in capacity_scales:
            inst = _scaled(base, ds, cs)
            out = mod.solve(inst, gap=gap, max_time=max_time)
            s = out["summary"]
            tstt = s.get("tstt")
            if tstt is None:
                tstt = sum(f["volume"] * (f["travel_time"] or 0)
                           for f in out["flows"]
                           if isinstance(f["travel_time"], (int, float)))
            vmt_proxy = sum(f["volume"] for f in out["flows"])
            rows.append(dict(demand_scale=ds, capacity_scale=cs,
                             solver=solver,
                             iterations=s.get("iterations"),
                             relative_gap=s.get("relative_gap"),
                             wall_time_s=s.get("wall_time_s"),
                             tstt=round(tstt, 1),
                             total_link_flow=round(vmt_proxy, 1)))
            tag = f"d{ds}_c{cs}".replace(".", "p")
            with open(outdir / f"link_performance_{tag}.csv", "w",
                      newline="") as f:
                w = csv.DictWriter(f, fieldnames=["from_node_id",
                                                  "to_node_id", "volume",
                                                  "travel_time"])
                w.writeheader()
                w.writerows(out["flows"])
    with open(outdir / "experiment_grid.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows
