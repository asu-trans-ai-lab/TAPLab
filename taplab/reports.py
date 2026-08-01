"""TAPReports: normalized run/compare/experiment reports and the
reproduce check against an instance's reference outputs."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path


def _flow_map(flows):
    return {(f["from_node_id"], f["to_node_id"]): f["volume"] for f in flows}


def write_run_report(inst, out, outdir: Path):
    s = out["summary"]
    lines = [f"# TAPLab run report — {inst.path.name} / {s['solver']}", "",
             f"- algorithm: {s.get('algorithm')}",
             f"- iterations: {s.get('iterations')}",
             f"- relative gap: {s.get('relative_gap')}",
             f"- wall time (s): {s.get('wall_time_s')}",
             f"- TSTT: {s.get('tstt')}",
             f"- links reported: {len(out['flows'])}", ""]
    ref = inst.path / "reference" / "link_performance.csv"
    if ref.exists():
        rf = {(int(float(r["from_node_id"])), int(float(r["to_node_id"]))):
              float(r["volume"])
              for r in csv.DictReader(open(ref, encoding="utf-8-sig"))}
        ours = _flow_map(out["flows"])
        common = set(rf) & set(ours)
        if common:
            rmse = math.sqrt(sum((ours[k] - rf[k]) ** 2 for k in common)
                             / len(common))
            denom = sum(abs(rf[k]) for k in common) / len(common)
            lines += ["## Reference comparison",
                      f"- common links: {len(common)}",
                      f"- flow RMSE vs reference: {rmse:,.3f} "
                      f"({100 * rmse / max(denom, 1e-9):.2f}% of mean flow)", ""]
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def write_compare_report(inst, results: dict, outdir: Path):
    names = list(results)
    lines = [f"# TAPLab comparison — {inst.path.name}", "",
             "| solver | iterations | relative gap | wall time (s) | TSTT |",
             "|---|---|---|---|---|"]
    for n in names:
        s = results[n]["summary"]
        lines.append(f"| {n} | {s.get('iterations')} | "
                     f"{s.get('relative_gap')} | {s.get('wall_time_s')} | "
                     f"{s.get('tstt')} |")
    lines.append("")
    lines.append("## Pairwise link-flow differences")
    lines.append("| pair | common links | RMSE | max abs diff |")
    lines.append("|---|---|---|---|")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            A = _flow_map(results[names[i]]["flows"])
            B = _flow_map(results[names[j]]["flows"])
            common = set(A) & set(B)
            if not common:
                lines.append(f"| {names[i]} vs {names[j]} | 0 | - | - |")
                continue
            diffs = [A[k] - B[k] for k in common]
            rmse = math.sqrt(sum(d * d for d in diffs) / len(common))
            lines.append(f"| {names[i]} vs {names[j]} | {len(common)} | "
                         f"{rmse:,.3f} | {max(abs(d) for d in diffs):,.3f} |")
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    for n in names:
        (outdir / f"summary_{n}.json").write_text(
            json.dumps(results[n]["summary"], indent=1))


def write_experiment_report(grid_rows, outdir: Path):
    lines = ["# TAPLab experiment report", "",
             "| demand x | capacity x | iterations | gap | time (s) | TSTT | total flow |",
             "|---|---|---|---|---|---|---|"]
    for r in grid_rows:
        lines.append(f"| {r['demand_scale']} | {r['capacity_scale']} | "
                     f"{r['iterations']} | {r['relative_gap']} | "
                     f"{r['wall_time_s']} | {r['tstt']} | "
                     f"{r['total_link_flow']} |")
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def reproduce(target: Path, root: Path):
    """Re-run the reference solver on an instance and verify against its
    stored reference outputs (the reproducibility check)."""
    from .instance import Instance
    from .adapters import reference_fw
    inst_dir = target if (target / "node.csv").exists() else root / "tapbench" / target.name
    inst = Instance.load(inst_dir)
    out = reference_fw.solve(inst, gap=1e-6)
    tmp = inst_dir / "reference"
    ref_summary = json.loads((tmp / "summary.json").read_text()) \
        if (tmp / "summary.json").exists() else {}
    print(json.dumps(dict(reproduced=out["summary"],
                          reference=ref_summary), indent=1))
