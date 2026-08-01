"""TAPDashboard: a static, dependency-free HTML dashboard built from
results/<instance>/<solver>/ runs. Sections follow the six dashboard pages:
overview cards, convergence comparison, solver comparison, spatial
difference analysis, and the reproducibility report. Open the generated
dashboard.html in any browser."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
from pathlib import Path

PALETTE = ["#245a8d", "#c0392b", "#1e8449", "#8e44ad", "#b7950b", "#16a085"]


def _load_runs(res_dir: Path):
    runs = {}
    for d in sorted(res_dir.iterdir()) if res_dir.exists() else []:
        if not d.is_dir() or not (d / "summary.json").exists():
            continue
        r = {"summary": json.loads((d / "summary.json").read_text()),
             "convergence": [], "flows": {}}
        cv = d / "convergence.csv"
        if cv.exists():
            for row in csv.DictReader(open(cv)):
                try:
                    r["convergence"].append(
                        (int(float(row["iteration"])),
                         float(row["relative_gap"]),
                         float(row["wall_time_s"]) if row.get("wall_time_s")
                         not in (None, "", "None") else None))
                except (ValueError, KeyError):
                    pass
        lp = d / "link_performance.csv"
        if lp.exists():
            for row in csv.DictReader(open(lp)):
                try:
                    k = (int(float(row["from_node_id"])),
                         int(float(row["to_node_id"])))
                    r["flows"][k] = float(row["volume"])
                except (ValueError, KeyError):
                    pass
        runs[d.name] = r
    return runs


def _svg_convergence(runs, x_axis="iteration"):
    """Log-scale relative-gap chart as inline SVG (no JS libraries)."""
    W, H, L, B = 640, 320, 60, 40
    series = []
    for i, (name, r) in enumerate(runs.items()):
        pts = [(it if x_axis == "iteration" else (tt or 0), g)
               for it, g, tt in r["convergence"] if g and g > 0]
        if pts:
            series.append((name, pts, PALETTE[i % len(PALETTE)]))
    if not series:
        return "<p><em>No convergence histories recorded.</em></p>"
    xmax = max(x for _, pts, _ in series for x, _ in pts) or 1
    gmin = min(g for _, pts, _ in series for _, g in pts)
    gmax = max(g for _, pts, _ in series for _, g in pts)
    lg0, lg1 = math.floor(math.log10(gmin)), math.ceil(math.log10(max(gmax, gmin * 10)))

    def X(x):
        return L + (W - L - 20) * x / xmax

    def Y(g):
        return H - B - (H - B - 20) * (math.log10(g) - lg0) / max(lg1 - lg0, 1)

    parts = [f'<svg viewBox="0 0 {W} {H}" style="max-width:100%;background:#fff">']
    for e in range(lg0, lg1 + 1):
        y = Y(10 ** e)
        parts.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W-20}" y2="{y:.1f}" stroke="#eee"/>'
                     f'<text x="{L-6}" y="{y+4:.1f}" text-anchor="end" font-size="11">1e{e}</text>')
    for name, pts, col in series:
        d = " ".join(f"{'M' if i == 0 else 'L'}{X(x):.1f},{Y(g):.1f}"
                     for i, (x, g) in enumerate(pts))
        parts.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.8"/>')
    for i, (name, _, col) in enumerate(series):
        parts.append(f'<rect x="{L+8}" y="{12+16*i}" width="12" height="4" fill="{col}"/>'
                     f'<text x="{L+26}" y="{18+16*i}" font-size="12">{name}</text>')
    xlabel = "iteration" if x_axis == "iteration" else "wall time (s)"
    parts.append(f'<text x="{(W+L)/2:.0f}" y="{H-8}" text-anchor="middle" font-size="12">{xlabel}</text>'
                 f'<text x="14" y="{H/2:.0f}" font-size="12" transform="rotate(-90 14 {H/2:.0f})" text-anchor="middle">relative gap</text></svg>')
    return "".join(parts)


def _sha1(p: Path):
    return hashlib.sha1(p.read_bytes()).hexdigest()[:12]


def build_dashboard(instance, res_dir: Path, out: Path):
    runs = _load_runs(res_dir)
    from .stats import network_statistics
    st = network_statistics(instance)

    # reference flows join
    ref = {}
    rp = instance.path / "reference" / "link_performance.csv"
    if rp.exists():
        for row in csv.DictReader(open(rp, encoding="utf-8-sig")):
            ref[(int(float(row["from_node_id"])),
                 int(float(row["to_node_id"])))] = float(row["volume"])

    def cards():
        c = [("Zones", st["zones"]), ("Nodes", st["physical_nodes"] + st["centroid_nodes"]),
             ("Links", st["links"]), ("Connectors", st["centroid_connectors"]),
             ("OD pairs", st["positive_demand_od_pairs"]),
             ("Total demand", f"{st['total_demand']:,.0f}"),
             ("OD coverage", f"{100*st['od_coverage']:.2f}%"),
             ("Solvers run", len(runs))]
        return "".join(f'<div class="card"><div class="v">{v}</div><div class="k">{k}</div></div>'
                       for k, v in c)

    def comp_table():
        rows = []
        for name, r in runs.items():
            s = r["summary"]
            if s.get("status") == "failed":
                rows.append(f"<tr><td>{name}</td><td colspan=6 style='color:#c0392b;text-align:left'>"
                            f"FAILED: {s.get('error','')}</td></tr>")
                continue
            rmse = ""
            if ref and r["flows"]:
                common = set(ref) & set(r["flows"])
                if common:
                    e = math.sqrt(sum((r["flows"][k] - ref[k]) ** 2
                                      for k in common) / len(common))
                    rmse = f"{e:,.1f}"
            rows.append(f"<tr><td>{name}</td><td>{s.get('algorithm','')}</td>"
                        f"<td>{s.get('iterations','')}</td>"
                        f"<td>{_fmt(s.get('relative_gap'))}</td>"
                        f"<td>{s.get('wall_time_s','')}</td>"
                        f"<td>{_fmt(s.get('tstt'))}</td><td>{rmse}</td></tr>")
        return ("<table><tr><th>Solver</th><th>Algorithm</th><th>Iterations</th>"
                "<th>Relative gap</th><th>Runtime (s)</th><th>TSTT</th>"
                "<th>Flow RMSE vs reference</th></tr>" + "".join(rows) + "</table>")

    def diff_table():
        names = list(runs)
        if len(names) < 2:
            return "<p><em>Run at least two solvers to compare spatially.</em></p>"
        A, B = runs[names[0]]["flows"], runs[names[1]]["flows"]
        common = sorted(set(A) & set(B),
                        key=lambda k: -abs(A[k] - B[k]))[:20]
        rows = "".join(f"<tr><td>({a},{b})</td><td>{A[(a,b)]:,.1f}</td>"
                       f"<td>{B[(a,b)]:,.1f}</td><td>{A[(a,b)]-B[(a,b)]:+,.1f}</td></tr>"
                       for a, b in common)
        return (f"<p>Top 20 link-flow disagreements: <b>{names[0]}</b> vs "
                f"<b>{names[1]}</b> ({len(set(A) & set(B))} common links).</p>"
                f"<table><tr><th>Link (from,to)</th><th>{names[0]}</th>"
                f"<th>{names[1]}</th><th>Difference</th></tr>{rows}</table>")

    def repro():
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"],
                                    capture_output=True, text=True,
                                    cwd=Path(__file__).parent).stdout.strip()[:12]
        except OSError:
            commit = "n/a"
        checks = "".join(f"<tr><td>{f}</td><td><code>{_sha1(instance.path / f)}</code></td></tr>"
                         for f in ("node.csv", "link.csv", "demand.csv")
                         if (instance.path / f).exists())
        return (f"<table><tr><th>Item</th><th>Value</th></tr>"
                f"<tr><td>TAPLab commit</td><td><code>{commit}</code></td></tr>"
                f"<tr><td>Python</td><td>{sys.version.split()[0]}</td></tr>"
                f"<tr><td>Platform</td><td>{platform.platform()}</td></tr>"
                f"</table><h3>Input checksums (SHA-1)</h3><table>"
                f"<tr><th>File</th><th>Digest</th></tr>{checks}</table>")

    html = f"""<!doctype html><meta charset="utf-8">
<title>TAPLab dashboard — {instance.path.name}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:24px auto;max-width:960px;color:#1c1c1c}}
h1{{border-bottom:3px solid #245a8d;padding-bottom:6px}}
h2{{color:#245a8d;margin-top:32px}}
.cards{{display:flex;flex-wrap:wrap;gap:10px}}
.card{{border:1px solid #ddd;border-radius:8px;padding:10px 16px;background:#f4f5f7;min-width:100px;text-align:center}}
.card .v{{font-size:20px;font-weight:600}} .card .k{{font-size:12px;color:#555}}
table{{border-collapse:collapse;margin:8px 0}} td,th{{border:1px solid #ccc;padding:4px 10px;font-size:13px;text-align:right}}
th{{background:#f4f5f7}} td:first-child,th:first-child{{text-align:left}}
</style>
<h1>TAPLab — {instance.path.name}</h1>
<p>Generated by <code>taplab dashboard</code>. All statistics computed from the
imported instance by TAPValidate; nothing is hard-coded.</p>
<h2>1&nbsp; Benchmark overview</h2><div class="cards">{cards()}</div>
<h2>2&nbsp; Convergence comparison</h2>
<h3>Relative gap vs iteration</h3>{_svg_convergence(runs, "iteration")}
<h3>Relative gap vs wall time</h3>{_svg_convergence(runs, "time")}
<h2>3&nbsp; Solver comparison</h2>{comp_table()}
<h2>4&nbsp; Spatial difference analysis</h2>{diff_table()}
<h2>5&nbsp; Reproducibility report</h2>{repro()}
"""
    out.write_text(html, encoding="utf-8")
    return out


def _fmt(x):
    if x is None or x == "":
        return ""
    if isinstance(x, float) and 0 < abs(x) < 1e-2:
        return f"{x:.2e}"
    if isinstance(x, (int, float)):
        return f"{x:,.2f}"
    return str(x)
