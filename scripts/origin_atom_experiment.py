"""B0 / L1 / L2 origin-atom experiment (ORIGIN_ATOM_SPEC.md, confirmed).

Instance: single-origin, 16-destination monotone (DAG) Manhattan grid,
n=16, medium congestion, fixed seed. Arms:

  B0        full origin/bush worker to 1e-5 (the reference)
  L1_J{2,4,8,16}  fixed primed origin atoms, latent gradient on lambda only
  L2        adaptive: latent gradient + stall-triggered B0 oracle atoms

Reported per arm: full-space certified gap, Beckmann objective, link-flow
error vs B0, bush sweeps consumed (the currency of the research question),
oracle calls, atoms, runtime. Chart: gap vs cumulative bush sweeps
(log gap) — B0's curve vs L2's.
"""
import csv
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taplab.instance import Instance                    # noqa: E402
from taplab.origin_atom import (OriginProblem, run_L1,  # noqa: E402
                                run_L2)

TOL = 1e-5
INST = "forge/origin_atom_grid16"


def main():
    inst = Instance.load(ROOT / "tapbench" / INST)
    P = OriginProblem(inst)
    print(f"instance: {P.m} arcs, {len(P.dests)} destinations, "
          f"demand {P.q_total:,.0f}", flush=True)
    outdir = ROOT / "results" / "origin_atom"
    outdir.mkdir(parents=True, exist_ok=True)

    hist_b0 = []
    xB, gapB, sweepsB, timeB = P.b0_solve(tol=TOL, history=hist_b0)
    objB = P.beckmann(xB)
    print(f"B0: gap {gapB:.2e} in {sweepsB} sweeps, {timeB:.2f}s, "
          f"obj {objB:,.1f}", flush=True)

    rows = [dict(arm="B0", gap=gapB, obj=objB, flow_err=0.0,
                 bush_sweeps=sweepsB, oracle_calls="", atoms="",
                 time_s=round(timeB, 3))]
    curves = [("B0", [(h["bush_sweeps"], h["gap"]) for h in hist_b0])]

    def flow_err(x):
        return float(np.linalg.norm(x - xB) / max(np.linalg.norm(xB), 1e-12))

    for J in (2, 4, 8, 16):
        r = run_L1(P, J, tol=TOL, seed=7)
        rows.append(dict(arm=f"L1_J{J}", gap=r["gap"], obj=r["obj"],
                         flow_err=flow_err(r["x"]),
                         bush_sweeps=r["bush_sweeps"], oracle_calls=0,
                         atoms=r["atoms"], time_s=round(r["time_s"], 3)))
        print(f"L1_J{J}: gap {r['gap']:.2e} obj {r['obj']:,.1f} "
              f"flow_err {rows[-1]['flow_err']:.3f} "
              f"bush_sweeps {r['bush_sweeps']}", flush=True)

    r = run_L2(P, J0=2, tol=TOL, seed=7)
    rows.append(dict(arm="L2", gap=r["gap"], obj=r["obj"],
                     flow_err=flow_err(r["x"]),
                     bush_sweeps=r["bush_sweeps"],
                     oracle_calls=r["oracle_calls"], atoms=r["atoms"],
                     time_s=round(r["time_s"], 3)))
    curves.append(("L2", [(h["bush_sweeps"], h["gap"])
                          for h in r["history"]]))
    print(f"L2: gap {r['gap']:.2e} obj {r['obj']:,.1f} "
          f"flow_err {rows[-1]['flow_err']:.3f} bush_sweeps "
          f"{r['bush_sweeps']} oracle_calls {r['oracle_calls']} "
          f"atoms {r['atoms']}", flush=True)

    with open(outdir / "results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # chart: certified gap (log) vs cumulative bush sweeps
    W, H, L, B = 640, 320, 70, 50
    pts = [(s, g) for _, c in curves for s, g in c if g > 0]
    smax = max(s for s, _ in pts) or 1
    gmin = min(g for _, g in pts)
    lg0, lg1 = math.floor(math.log10(gmin)), 1

    def X(s):
        return L + (W - L - 20) * s / smax

    def Y(g):
        return H - B - (H - B - 30) * (math.log10(max(g, gmin)) - lg0) / (lg1 - lg0)

    s_ = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
          f'style="background:#fff">',
          f'<text x="{W/2}" y="16" text-anchor="middle" font-size="13" '
          f'font-weight="bold">Certified full-space gap vs bush sweeps '
          f'consumed — B0 vs L2 (adaptive origin atoms)</text>']
    for e in range(lg0, lg1 + 1):
        y = Y(10 ** e)
        s_.append(f'<line x1="{L}" y1="{y:.0f}" x2="{W-20}" y2="{y:.0f}" '
                  f'stroke="#eee"/><text x="{L-5}" y="{y+4:.0f}" '
                  f'text-anchor="end" font-size="10">1e{e}</text>')
    for name, c, col in (("B0", curves[0][1], "#1c1c1c"),
                         ("L2", curves[1][1], "#c0392b")):
        d = " ".join(f"{'M' if i == 0 else 'L'}{X(s):.1f},{Y(g):.1f}"
                     for i, (s, g) in enumerate(c) if g > 0)
        s_.append(f'<path d="{d}" fill="none" stroke="{col}" '
                  f'stroke-width="2"/>')
    s_.append(f'<rect x="{L+10}" y="26" width="12" height="4" fill="#1c1c1c"/>'
              f'<text x="{L+26}" y="32" font-size="11">B0 (every point costs '
              f'a bush sweep)</text>'
              f'<rect x="{L+10}" y="42" width="12" height="4" fill="#c0392b"/>'
              f'<text x="{L+26}" y="48" font-size="11">L2 (latent sweeps are '
              f'free on this axis; steps = oracle calls)</text>'
              f'<text x="{(W+L)/2:.0f}" y="{H-10}" text-anchor="middle" '
              f'font-size="11">cumulative full bush sweeps</text></svg>')
    (outdir / "chart_gap_vs_sweeps.svg").write_text("".join(s_),
                                                    encoding="utf-8")
    print(f"-> {outdir}", flush=True)


if __name__ == "__main__":
    main()
