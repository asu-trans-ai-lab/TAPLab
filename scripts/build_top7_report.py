"""Build the complete top-7 STAP / latent-atom report into reports/
(tracked in git — the repository is private; the folder is additionally
marked internal, not for release).

Sources: results/stap_top5/comparison.csv (five solver arms),
results/stap_top5/cpp_arms.csv (C++ fixed-pool arms + decomposition rows),
results/latent_atom_comparison/ (k-sweep + convergence SVGs).
Rerun any time; the report regenerates in place.
"""
import csv
import datetime
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "2026-08_stap_top7_latent_atom"
R5 = ROOT / "results" / "stap_top5"
RLA = ROOT / "results" / "latent_atom_comparison"

DESC = {"forge/ladder_grid5": "grid 5x5, route-rich, high congestion",
        "forge/ladder_grid10": "grid 10x10, route-rich",
        "forge/ladder_grid20": "grid 20x20, route-rich",
        "forge/ladder_grid40": "grid 40x40, route-rich (1,756 nodes)",
        "forge/sts5x20_s1": "space-time 5x5 grid x 20 steps (A4)",
        "forge/sts8x30_s1": "space-time 8x8 grid x 30 steps (A4)",
        "sioux_falls": "Sioux Falls (path-poor classic)",
        "chicago_sketch": "Chicago Sketch (933 nodes, 2,950 links)"}


def load(path):
    return list(csv.DictReader(open(path))) if path.exists() else []


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    top5 = load(R5 / "comparison.csv")
    cpp = load(R5 / "cpp_arms.csv")
    ksweep = load(RLA / "comparison.csv")
    for f in (R5 / "comparison.csv", R5 / "cpp_arms.csv",
              RLA / "comparison.csv"):
        if f.exists():
            shutil.copy(f, OUT / f"{f.parent.name}_{f.name}")
    for svg in RLA.glob("convergence_*.svg"):
        shutil.copy(svg, OUT / svg.name)

    def fmt(x, spec=".2e"):
        try:
            return format(float(x), spec)
        except (TypeError, ValueError):
            return x or ""

    L = []
    L.append("# STAP Top-7 Comparison and Latent-Atom Performance Report")
    L.append("")
    L.append(f"*Internal — not for release. Generated {datetime.date.today()} "
             "by scripts/build_top7_report.py; all numbers reproduce from the "
             "committed harnesses.*")
    L.append("")
    L.append("## Protocol")
    L.append("")
    L.append("Gap target 1e-5. Seven algorithm arms: **tapb_B** (Dial's "
             "Algorithm B, C), **task_TAPAS / task_LUCE / task_BFW** (TAsK, "
             "C++), **latent_ol1** (adaptive latent-atom GP, k=8 majors, "
             "Python kernel, full-network pricing), **colcpp_full** "
             "(Jayakrishnan-style GP + elimination, CompressedTAP C++ engine, "
             "fixed K=32 penalty-KSP pool) and **colcpp_latent** (same engine, "
             "explicit majors + one nonnegative atom per OD). Each instance "
             "also carries a **decomposition row**: H0 (Bertsekas-style "
             "full-simplex projected gradient) / R0 (full GP, elimination) / "
             "R1 (latent) with the identity S_R x S_C|R = S_RC. Every "
             "flow-producing run is re-certified by the independent validator "
             "(recomputed costs, Beckmann objective, conservation, "
             "shortest-path bound). Fixed-pool gaps are restricted-master "
             "gaps; the full-network gap is always recomputed separately — "
             "the two are never conflated.")
    L.append("")

    insts = list(dict.fromkeys(r["instance"] for r in top5))
    for inst in insts:
        L.append(f"## {inst} — {DESC.get(inst, '')}")
        L.append("")
        L.append("| arm | time (s) | network gap (recomputed) | pool gap | TSTT | certified |")
        L.append("|---|---:|---:|---:|---:|---|")
        for r in top5:
            if r["instance"] != inst:
                continue
            ok = r.get("certified")
            gap = fmt(r.get("recomputed_gap"))
            note = "FAILED (no flows)" if gap.startswith("-1") else ok
            L.append(f"| {r['arm']} | {r.get('time_s','')} | {gap} | — | "
                     f"{fmt(r.get('tstt'), ',.0f')} | {note} |")
        for r in cpp:
            if r["instance"] != inst or r["arm"].startswith("decomp"):
                continue
            L.append(f"| {r['arm']} (K=32 pool) | {r.get('time_s','')} | "
                     f"{fmt(r.get('fullnet_gap'))} | {fmt(r.get('pool_gap'))} | "
                     f"{fmt(r.get('tstt'), ',.0f')} | "
                     f"conservation {'ok' if r.get('conservation_ok')=='True' else r.get('conservation_ok','')} |")
        for r in cpp:
            if r["instance"] == inst and r["arm"].startswith("decomp") \
                    and r.get("engine"):
                m = re.search(r"S_R=([\d.eE+-]+) S_C\|R_atom=([\d.eE+-]+) "
                              r"S_RC_atom=([\d.eE+-]+)", r["engine"])
                oe = re.search(r"oe_R1atom=([\d.eE+-]+)", r["engine"])
                if m:
                    L.append("")
                    L.append(f"Decomposition (Bertsekas-PG H0 / Jayakrishnan-GP R0 / "
                             f"latent R1): S_R = {m.group(1)}, S_C|R = "
                             f"{m.group(2)}, S_RC = {m.group(3)}"
                             + (f"; atom objective error {oe.group(1)}" if oe else ""))
        if not any(r["instance"] == inst for r in cpp):
            L.append("")
            L.append("*C++ fixed-pool arms: pending (pool generation in "
                     "progress at report time; rerun the generator to "
                     "refresh).*")
        L.append("")

    L.append("## Latent-atom k-sweep (adaptive, full-network certified)")
    L.append("")
    L.append("| instance | arm | iters | gap | time (s) | active cols | folded | atoms |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|")
    for r in ksweep:
        L.append(f"| {r['instance']} | {r['arm']} | {r.get('iterations','')} | "
                 f"{fmt(r.get('gap'))} | {r.get('time_s','')} | "
                 f"{r.get('cols_active','')} | {r.get('cols_folded','')} | "
                 f"{r.get('atoms','')} |")
    L.append("")

    L.append("## Findings")
    L.append("")
    L.append("1. **Bush methods dominate one-shot full-network solving at "
             "scale.** grid40: Algorithm B 4.2 s, TAPAS 6.0 s vs BFW 79.9 s, "
             "LUCE capped at 600 s (1.7e-4); Chicago Sketch: B 0.65 s.")
    L.append("2. **The latent atom is the best compression layer for "
             "path-based methods**: same engine, same pool, atom on/off gives "
             "1.05-1.7x end-to-end (S_C|R 1.4-4.2x on the solve itself) at "
             "1e-6-level objective error. Its edge grows with pool richness "
             "and congestion; on path-poor pools it is a no-op by "
             "construction.")
    L.append("3. **Adaptive OL1 is the only path-based arm that survives "
             "every track**, including the space-time instances where all "
             "three TAsK algorithms returned no flows; it is fastest overall "
             "on small route-rich grids (grid5: 0.023 s, ahead of B and "
             "TAPAS).")
    L.append("4. **Over-compression fails by churn, not accuracy** (k=2 on "
             "grid20-rich: 43,778 columns generated, 20,333 folded, iteration "
             "cap) — the atom budget must exceed equilibrium path "
             "multiplicity.")
    L.append("5. **Pool adequacy is the binding constraint for fixed-pool "
             "methods**: K=32 penalty-KSP pools solve to 1e-5 pool gaps but "
             "leave 8e-5 to 5.5e-3 full-network gaps — identical for full and "
             "latent, so the atom costs nothing, but only network-wide "
             "pricing certifies equilibrium.")
    L.append("6. **LUCE degrades sharply on route-rich congested grids** "
             "(100 s on grid20 vs TAPAS 0.57 s) — an origin-based sensitivity "
             "worth a dedicated study.")
    L.append("")
    L.append("## Reconciliation with published results")
    L.append("")
    L.append("- origin_bush_latent (monotone grids): O0 bush 89-431x over P0; "
             "OL1/P0 crossover ~7x7 — both reproduced here on general grids.")
    L.append("- column_solver (frozen pools): S_C|R 1.1-4.9x — matched "
             "(1.4-4.2x).")
    L.append("- Paper 2 / TSL: latent-atom GP ~110x over full path GP on "
             "K15 Sketch pools, within 15% of Algorithm B; active-set gives "
             "zero reduction under Logit-SUE, the atom 43-62% — the "
             "stochastic-choice case remains the atom's strongest ground.")
    L.append("- TSL slides: top 20% of pool paths carry 93.3% of nominal flow "
             "on Chicago Sketch — the major/minor split premise; randomized "
             "SVD (Halko-Martinsson-Tropp) is the at-scale basis "
             "constructor for the r-dimensional minor space.")
    L.append("")
    L.append("## Reproduce")
    L.append("")
    L.append("```")
    L.append("python scripts/stap_top5_comparison.py     # five solver arms")
    L.append("python scripts/stap_cpp_arms.py            # C++ fixed-pool arms")
    L.append("python scripts/latent_atom_comparison.py   # k-sweep")
    L.append("python scripts/build_top7_report.py        # this report")
    L.append("```")
    (OUT / "README.md").write_text("\n".join(L), encoding="utf-8")
    print(f"-> {OUT / 'README.md'}")


if __name__ == "__main__":
    main()
