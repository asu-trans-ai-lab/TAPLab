"""TAPLab command-line interface.

  taplab stats <name|dir>
  taplab validate <name|dir>
  taplab run <name|dir> --solver reference_fw [--algorithm fw] [--gap 1e-6]
  taplab bench <name|dir> --solvers reference_fw,tapb
  taplab compare <name|dir> --solvers reference_fw,taplite
  taplab experiment <name|dir> --demand-scale 0.8,1.0,1.2 --capacity-scale 0.8,1.0
  taplab dashboard <name|dir>
  taplab view <name|dir>
  taplab reproduce <instance_dir>
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
    cand = ROOT / "tapbench" / str(name_or_dir)
    if cand.exists():
        return cand
    sys.exit(f"instance not found: {name_or_dir}")


def cmd_stats(a):
    from .stats import write_stats
    inst = Instance.load(_resolve(a.instance))
    print(json.dumps(write_stats(inst), indent=1))


def cmd_dashboard(a):
    from .dashboard import build_dashboard
    inst_dir = _resolve(a.instance)
    inst = Instance.load(inst_dir)
    res = ROOT / "results" / inst_dir.name
    out = build_dashboard(inst, res, res / "dashboard.html")
    print(f"-> {out}")


def cmd_verify(a):
    from .verify import verify
    inst_dir = _resolve(a.instance)
    inst = Instance.load(inst_dir)
    lp = ROOT / "results" / inst_dir.name / a.solver / "link_performance.csv"
    if not lp.exists():
        sys.exit(f"no run found: {lp}")
    self_gap = None
    sj = lp.parent / "summary.json"
    if sj.exists():
        self_gap = json.loads(sj.read_text()).get("relative_gap")
    rep = verify(inst, lp,
                 gap_target=float(a.gap_target) if a.gap_target else None,
                 self_reported_gap=self_gap)
    (lp.parent / "validation_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    sys.exit(0 if rep["certified"] else 1)


def cmd_view(a):
    from .view import build_view
    inst_dir = _resolve(a.instance)
    inst = Instance.load(inst_dir)
    res = ROOT / "results" / inst_dir.name
    res.mkdir(parents=True, exist_ok=True)
    out = build_view(inst, res, res / "view.html")
    print(f"-> {out}")


def cmd_bench(a):
    """Run every named solver, then build the comparison dashboard."""
    for sname in a.solvers.split(","):
        a2 = argparse.Namespace(instance=a.instance, solver=sname.strip(),
                                algorithm=a.algorithm, gap=a.gap,
                                max_time=a.max_time)
        try:
            cmd_run(a2)
        except SystemExit:
            raise
        except Exception as e:
            # failures stay in the result table: record, then keep going
            print(f"[bench] {sname} failed: {e}", file=sys.stderr)
            fdir = ROOT / "results" / _resolve(a.instance).name / sname.strip()
            fdir.mkdir(parents=True, exist_ok=True)
            (fdir / "summary.json").write_text(json.dumps(
                dict(solver=sname.strip(), status="failed",
                     error=str(e)[:500]), indent=1))
    cmd_dashboard(a)


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
        w = csv.DictWriter(f, fieldnames=["link_id", "from_node_id",
                                          "to_node_id", "volume",
                                          "travel_time"], extrasaction="ignore")
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

    p = sub.add_parser("stats")
    p.add_argument("instance")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("dashboard")
    p.add_argument("instance")
    p.set_defaults(fn=cmd_dashboard)

    p = sub.add_parser("view")
    p.add_argument("instance")
    p.set_defaults(fn=cmd_view)

    p = sub.add_parser("verify")
    p.add_argument("instance")
    p.add_argument("--solver", required=True)
    p.add_argument("--gap-target", default=None)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("ksp")
    p.add_argument("instance")
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--penalty", type=float, default=1.5)
    p.set_defaults(fn=lambda a: __import__("taplab.ksp", fromlist=["write_pool"])
                   .write_pool(Instance.load(_resolve(a.instance)),
                               a.k, a.penalty))

    p = sub.add_parser("forge", add_help=False)
    p.set_defaults(fn=lambda a: __import__("taplab.forge", fromlist=["main"])
                   .main(a.forge_args))
    p.add_argument("forge_args", nargs=argparse.REMAINDER)

    p = sub.add_parser("bench")
    p.add_argument("instance")
    p.add_argument("--solvers", default="reference_fw")
    p.add_argument("--algorithm", default="fw")
    p.add_argument("--gap", default="1e-4")
    p.add_argument("--max-time", type=int, default=600)
    p.set_defaults(fn=cmd_bench)

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
