"""Latent-atom comparison experiment.

Arms (identical Python kernel for the latent_gp family, so differences are
representation, not shortest-path implementation):
  p0        explicit-path GP, adaptive column generation (no compression)
  ol1_k2/4/8  latent-atom GP with max_explicit = 2 / 4 / 8 major columns
  tapb_B    Dial's Algorithm B (native C, bush representation) as the
            bush-side reference

Instances span the path-richness ladder: path-poor (Sioux Falls, Anaheim),
route-rich forge grids (the controlled latent-atom testbed), the A1
one-to-many origin structure, and Chicago Sketch (real intermediate).

Outputs: results/latent_atom_comparison/{comparison.csv, report.md,
convergence_<instance>.svg}
"""
import csv
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taplab.instance import Instance          # noqa: E402
from taplab.adapters import latent_gp         # noqa: E402
from taplab.verify import verify              # noqa: E402

GAP = 1e-5
INSTANCES = [
    ("sioux_falls", "path-poor classic", 60),
    ("anaheim", "path-poor classic", 120),
    ("forge/grid12_rich_s7", "route-rich grid", 120),
    ("forge/grid20_rich_s11", "route-rich grid, high congestion", 300),
    ("forge/grid16_one2many_s3", "A1 one origin - 16 destinations", 120),
    ("chicago_sketch", "real intermediate", 420),
]
ARMS = [("p0", dict(algorithm="p0")),
        ("ol1_k2", dict(algorithm="ol1", max_explicit=2)),
        ("ol1_k4", dict(algorithm="ol1", max_explicit=4)),
        ("ol1_k8", dict(algorithm="ol1", max_explicit=8))]

PALETTE = {"p0": "#1c1c1c", "ol1_k2": "#c0392b", "ol1_k4": "#245a8d",
           "ol1_k8": "#1e8449", "tapb_B": "#8e44ad"}


def run_tapb(inst, max_time):
    exe = os.environ.get("TAPLAB_TAPB_EXE")
    if not exe:
        return None
    from taplab.adapters import tapb
    try:
        return tapb.solve(inst, gap=GAP, max_time=max_time)
    except Exception as e:
        print(f"  tapb failed: {e}")
        return None


def svg_convergence(curves, out_path, title):
    W, H, L, B = 640, 300, 60, 40
    pts_all = [(x, g) for _, series in curves for x, g in series if g and g > 0]
    if not pts_all:
        return
    xmax = max(x for x, _ in pts_all) or 1
    gmin = min(g for _, g in pts_all)
    lg0 = math.floor(math.log10(gmin))
    lg1 = 0

    def X(x):
        return L + (W - L - 20) * x / xmax

    def Y(g):
        return H - B - (H - B - 30) * (math.log10(g) - lg0) / max(lg1 - lg0, 1)

    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" style="background:#fff">',
         f'<text x="{(W+L)/2:.0f}" y="16" text-anchor="middle" font-size="13" font-weight="bold">{title}</text>']
    for e in range(lg0, lg1 + 1):
        y = Y(10 ** e)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-20}" y2="{y:.1f}" stroke="#eee"/>'
                 f'<text x="{L-6}" y="{y+4:.1f}" text-anchor="end" font-size="10">1e{e}</text>')
    for i, (name, series) in enumerate(curves):
        col = PALETTE.get(name, "#888")
        d = " ".join(f"{'M' if j == 0 else 'L'}{X(x):.1f},{Y(g):.1f}"
                     for j, (x, g) in enumerate(series) if g > 0)
        s.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.8"/>')
        s.append(f'<rect x="{L+10}" y="{24+14*i}" width="12" height="4" fill="{col}"/>'
                 f'<text x="{L+26}" y="{30+14*i}" font-size="11">{name}</text>')
    s.append(f'<text x="{(W+L)/2:.0f}" y="{H-8}" text-anchor="middle" font-size="11">wall time (s)</text></svg>')
    out_path.write_text("".join(s), encoding="utf-8")


def main():
    outdir = ROOT / "results" / "latent_atom_comparison"
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for inst_name, desc, cap in INSTANCES:
        inst = Instance.load(ROOT / "tapbench" / inst_name)
        print(f"== {inst_name} ({desc})")
        curves = []
        for arm, kw in ARMS:
            out = latent_gp.solve(inst, gap=GAP, max_time=cap,
                                  max_iter=2000, **kw)
            s = out["summary"]
            # independent certification of the final flows
            lp = outdir / f"lp_{inst_name.replace('/', '_')}_{arm}.csv"
            with open(lp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["link_id", "from_node_id",
                                                  "to_node_id", "volume",
                                                  "travel_time"],
                                   extrasaction="ignore")
                w.writeheader()
                w.writerows(out["flows"])
            rep = verify(inst, lp, self_reported_gap=s["relative_gap"])
            lp.unlink()
            rows.append(dict(instance=inst_name, arm=arm,
                             iterations=s["iterations"],
                             gap=s["relative_gap"],
                             time_s=s["wall_time_s"],
                             tstt=s["tstt"],
                             sp_calls=s["shortest_path_calls"],
                             cols_active=s["columns_active"],
                             cols_generated=s["columns_generated"],
                             cols_folded=s["columns_folded"],
                             atoms=s["latent_atoms"],
                             certified=rep["certified"],
                             recomputed_gap=rep["relative_gap_recomputed"]))
            curves.append((arm, [(t, g) for _, g, t in out["convergence"]]))
            print(f"  {arm}: it={s['iterations']} gap={s['relative_gap']:.1e} "
                  f"t={s['wall_time_s']}s cols={s['columns_active']} "
                  f"atoms={s['latent_atoms']} certified={rep['certified']}")
        tb = run_tapb(inst, cap)
        if tb:
            s = tb["summary"]
            rows.append(dict(instance=inst_name, arm="tapb_B",
                             iterations=s.get("iterations"),
                             gap=s.get("relative_gap"),
                             time_s=s.get("wall_time_s"),
                             tstt=s.get("tstt"), sp_calls="",
                             cols_active="", cols_generated="",
                             cols_folded="", atoms="", certified="",
                             recomputed_gap=""))
            curves.append(("tapb_B", [(t or 0, g) for _, g, t in
                                      tb["convergence"]]))
            print(f"  tapb_B: gap={s.get('relative_gap')} t={s.get('wall_time_s')}s")
        svg_convergence(curves,
                        outdir / f"convergence_{inst_name.replace('/', '_')}.svg",
                        f"{inst_name} — relative gap vs time")

    with open(outdir / "comparison.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    lines = ["# Latent-atom algorithm comparison", "",
             f"Gap target {GAP:g}; identical Python kernel across the "
             "latent_gp arms (differences are representation, not routing); "
             "tap-b Algorithm B (native C) as the bush-side reference. "
             "Every latent_gp result is independently certified.", ""]
    for inst_name, desc, _ in INSTANCES:
        lines += [f"## {inst_name} — {desc}", "",
                  "| arm | iters | gap | time (s) | SP calls | active cols | folded | atoms | certified |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if r["instance"] == inst_name:
                g = f"{r['gap']:.1e}" if isinstance(r["gap"], float) else r["gap"]
                lines.append(f"| {r['arm']} | {r['iterations']} | {g} | "
                             f"{r['time_s']} | {r['sp_calls']} | "
                             f"{r['cols_active']} | {r['cols_folded']} | "
                             f"{r['atoms']} | {r['certified']} |")
        lines.append("")
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"-> {outdir}")


if __name__ == "__main__":
    main()
