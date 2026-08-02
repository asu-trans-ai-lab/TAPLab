"""B5 scenario-reuse experiment: does the frozen latent-atom model pay off
across perturbed scenarios?

Protocol per instance:
 1. penalty-KSP pool (K=32) — shared setup
 2. base solve: full-pool GP (cold) -> nominal x0; fixes the atom model
    (anchor + 6 majors + one fixed nominal-share atom per OD)
 3. per scenario (demand x capacity scaling grid):
      compressed re-solve : atom model, warm-started from previous masses
      full re-solve       : full pool GP, cold (the honest baseline)
    both to the same represented-column gap 1e-6
 4. metrics: per-scenario time, objective error of compressed vs full,
    break-even scenario count (setup+base amortization), and accuracy decay
    as scenarios drift from base

Outputs: results/scenario_reuse/{scenarios.csv, report.md}
"""
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taplab.instance import Instance                     # noqa: E402
from taplab.ksp import generate_pool                     # noqa: E402
from taplab.scenario_reuse import (build_pool_arrays, full_model,  # noqa: E402
                                   atom_model, gp_solve)

TOL = 1e-6
MAJ_CAP = 6
POOL_K = 32
SCENARIOS = [(0.90, 1.0), (0.95, 1.0), (1.05, 1.0), (1.10, 1.0),
             (1.20, 1.0), (1.00, 0.9), (1.10, 0.9), (1.30, 1.0)]
INSTANCES = ["sioux_falls", "forge/ladder_grid20"]


def run(inst_name):
    inst = Instance.load(ROOT / "tapbench" / inst_name)
    t0 = time.time()
    pool = generate_pool(inst, POOL_K, 1.5)
    P = build_pool_arrays(inst, pool)
    t_pool = time.time() - t0
    print(f"== {inst_name}: pool {len(P['paths']):,} paths "
          f"({t_pool:.2f}s), {P['n_od']} ODs", flush=True)

    base_cols = full_model(P)
    base = gp_solve(P, base_cols, tol=TOL)
    x0 = base["v"] * 0.0
    x0p = [sum(c["mass"] for c in od for _ in [0]) for od in base_cols]
    # nominal per-path flows for the atom split
    import numpy as np
    x0 = np.zeros(len(P["paths"]))
    k = 0
    for od in base_cols:
        for c in od:
            x0[k] = c["mass"]
            k += 1
    print(f"  base full-pool solve: {base['time_s']}s gap {base['gap']:.1e}",
          flush=True)

    acols = atom_model(P, x0, MAJ_CAP)
    n_full = sum(len(od) for od in base_cols)
    n_comp = sum(len(od) for od in acols)
    rows = []
    cum_c = t_pool + base["time_s"]
    cum_f = 0.0
    for (ds, cs) in SCENARIOS:
        f = gp_solve(P, full_model(P), dscale=ds, cscale=cs, tol=TOL)
        c = gp_solve(P, acols, dscale=ds, cscale=cs, tol=TOL, warm=True)
        cum_f += f["time_s"]
        cum_c += c["time_s"]
        oe = abs(c["obj"] - f["obj"]) / max(abs(f["obj"]), 1e-30)
        rows.append(dict(instance=inst_name, demand_scale=ds,
                         capacity_scale=cs,
                         full_s=f["time_s"], comp_s=c["time_s"],
                         speedup=round(f["time_s"] / max(c["time_s"], 1e-9), 2),
                         full_gap=f["gap"], comp_gap=c["gap"],
                         obj_err=oe, cum_full=round(cum_f, 3),
                         cum_comp=round(cum_c, 3)))
        print(f"  d{ds} c{cs}: full {f['time_s']}s vs compressed "
              f"{c['time_s']}s (x{rows[-1]['speedup']}) obj_err {oe:.2e}",
              flush=True)
    return rows, dict(instance=inst_name, pool_s=round(t_pool, 2),
                      base_s=base["time_s"], n_cols_full=n_full,
                      n_cols_comp=n_comp,
                      reduction_pct=round(100 * (1 - n_comp / n_full), 1))


def main():
    outdir = ROOT / "results" / "scenario_reuse"
    outdir.mkdir(parents=True, exist_ok=True)
    allrows, setups = [], []
    for inst in INSTANCES:
        rows, setup = run(inst)
        allrows += rows
        setups.append(setup)
    with open(outdir / "scenarios.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allrows[0].keys()))
        w.writeheader()
        w.writerows(allrows)

    L = ["# B5 scenario reuse: frozen latent-atom model vs full re-solve", ""]
    for s in setups:
        L += [f"## {s['instance']}",
              f"Setup: pool {s['pool_s']}s + base solve {s['base_s']}s; "
              f"columns {s['n_cols_full']} -> {s['n_cols_comp']} "
              f"({s['reduction_pct']}% reduction, maj_cap={MAJ_CAP})", "",
              "| demand x | capacity x | full (s) | compressed (s) | speedup | obj err | cum full | cum compressed |",
              "|---|---|---|---|---|---|---|---|"]
        for r in allrows:
            if r["instance"] == s["instance"]:
                L.append(f"| {r['demand_scale']} | {r['capacity_scale']} | "
                         f"{r['full_s']} | {r['comp_s']} | {r['speedup']}x | "
                         f"{r['obj_err']:.2e} | {r['cum_full']} | "
                         f"{r['cum_comp']} |")
        # break-even: first scenario count where cumulative compressed
        # (incl. setup) undercuts cumulative full
        be = None
        for i, r in enumerate([x for x in allrows
                               if x["instance"] == s["instance"]], 1):
            if r["cum_comp"] < r["cum_full"]:
                be = i
                break
        L += ["", f"Break-even (incl. pool + base setup): "
              + (f"scenario {be}" if be else
                 "not reached within this scenario set"), ""]
    (outdir / "report.md").write_text("\n".join(L), encoding="utf-8")
    print(f"-> {outdir}", flush=True)


if __name__ == "__main__":
    main()
