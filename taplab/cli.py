"""TAPLab command-line interface.

  taplab validate <instance_dir>
  taplab run <name|dir> --solver reference_fw [--algorithm fw] [--gap 1e-6]
  taplab compare <name|dir> --solvers reference_fw,taplite
  taplab experiment <name|dir> --demand-scale 0.8,1.0,1.2 --capacity-scale 0.8,1.0
  taplab reproduce <experiment.yml|results_dir>
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import adapters
from .instance import Instance
from .validate import validate
from .reports import write_run_report, write_compare_report, write_experiment_report

ROOT = Path(__file__).resolve().parent.parent


def _resolve(name_or_dir) -> Path:
    p = Path(name_or_dir)
    if p.exists():
        return p
    cand = ROOT / "instances" / str(name_or_dir)
    if cand.exists():
        return cand
    sys.exit(f"instance not found: {name_or_dir}")


def cmd_validate(a):
    inst = Instance.load(_resolve(a.instance))
    rep = validate(inst)
    print(json.dumps(rep, indent=1))
    sys.exit(0 if rep["pass"] else 1)


def cmd_run(a):
    inst_dir = _resolve(a.instance)
    inst = Instance.load(inst_dir)
    rep = validate(inst)
    if not rep["pass"]:
        sys.exit("validation failed:\n" + "\n".join(rep["errors"]))
    mod = adapters.get(a.solver)
    out = mod.solve(inst, algorithm=a.algorithm, gap=float(a.gap),
                    max_time=a.max_time)
    outdir = ROOT / "results" / inst_dir.name / a.solver
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "link_performance.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["from_node_id", "to_node_id",
                                          "volume", "travel_time"])
        w.writeheader()
        w.writerows(out["flows"])
    with open(outdir / "convergence.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["iteration", "relative_gap", "wall_time_s"])
        w.writerows(out["convergence"])
    (outdir / "summary.json").write_text(json.dumps(out["summary"], indent=1))
    write_run_report(inst, out, outdir)
    print(json.dumps(out["summary"], indent=1))
    print(f"-> {outdir}")


def cmd_compare(a):
    inst_dir = _resolve(a.instance)
    inst = Instance.load(inst_dir)
    results = {}
    for sname in a.solvers.split(","):
        sname = sname.strip()
        mod = adapters.get(sname)
        results[sname] = mod.solve(inst, algorithm=a.algorithm,
                                   gap=float(a.gap), max_time=a.max_time)
    outdir = ROOT / "results" / inst_dir.name / "compare"
    outdir.mkdir(parents=True, exist_ok=True)
    write_compare_report(inst, results, outdir)
    print(f"-> {outdir / 'report.md'}")


def cmd_experiment(a):
    inst_dir = _resolve(a.instance)
    from .experiment import run_experiment
    outdir = ROOT / "results" / inst_dir.name / "experiment"
    grid = run_experiment(
        inst_dir,
        solver=a.solver,
        demand_scales=[float(x) for x in a.demand_scale.split(",")],
        capacity_scales=[float(x) for x in a.capacity_scale.split(",")],
        gap=float(a.gap), max_time=a.max_time, outdir=outdir)
    write_experiment_report(grid, outdir)
    print(f"-> {outdir / 'report.md'}")


def cmd_reproduce(a):
    from .reports import reproduce
    reproduce(Path(a.target), ROOT)


def main():
    ap = argparse.ArgumentParser(prog="taplab", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate")
    p.add_argument("instance")
    p.set_defaults(fn=cmd_validate)

    for name, fn in [("run", cmd_run)]:
        p = sub.add_parser(name)
        p.add_argument("instance")
        p.add_argument("--solver", default="reference_fw")
        p.add_argument("--algorithm", default="fw")
        p.add_argument("--gap", default="1e-6")
        p.add_argument("--max-time", type=int, default=600)
        p.set_defaults(fn=fn)

    p = sub.add_parser("compare")
    p.add_argument("instance")
    p.add_argument("--solvers", required=True)
    p.add_argument("--algorithm", default="fw")
    p.add_argument("--gap", default="1e-6")
    p.add_argument("--max-time", type=int, default=600)
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("experiment")
    p.add_argument("instance")
    p.add_argument("--solver", default="reference_fw")
    p.add_argument("--demand-scale", default="1.0")
    p.add_argument("--capacity-scale", default="1.0")
    p.add_argument("--gap", default="1e-5")
    p.add_argument("--max-time", type=int, default=600)
    p.set_defaults(fn=cmd_experiment)

    p = sub.add_parser("reproduce")
    p.add_argument("target")
    p.set_defaults(fn=cmd_reproduce)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
