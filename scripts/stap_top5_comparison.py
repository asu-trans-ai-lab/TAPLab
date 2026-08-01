"""Top-5 STAP algorithm comparison across the scale ladder.

Arms (the five leading algorithms from the solver assessment, including the
latent-atom line):
  tapb_B       Dial's Algorithm B          (bush, native C)
  task_TAPAS   TAPAS                       (bush/PAS, native C++)
  task_LUCE    LUCE                        (origin-based, native C++)
  task_BFW     bi-conjugate Frank-Wolfe    (link-based, native C++)
  latent_ol1   latent-atom GP, k=8 majors  (compressed path, Python kernel)

Instances: the standard opening — grid scale ladder n = 5/10/20/40 (route-
rich configuration, seeded) and space-time expanded networks (A4), plus
Sioux Falls and Chicago Sketch anchors. Every run's flows are re-certified
by the independent validator; the native arms' timings measure the solver
end-to-end through the adapter (conversion included).

Outputs: results/stap_top5/{comparison.csv, report.md}
"""
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taplab.instance import Instance          # noqa: E402
from taplab import adapters                   # noqa: E402
from taplab.verify import verify              # noqa: E402

GAP = 1e-5
INSTANCES = [
    ("forge/ladder_grid5", 120), ("forge/ladder_grid10", 200),
    ("forge/ladder_grid20", 400), ("forge/ladder_grid40", 600),
    ("forge/sts5x20_s1", 300), ("forge/sts8x30_s1", 600),
    ("sioux_falls", 120), ("chicago_sketch", 600),
]
ARMS = [
    ("tapb_B", "tapb", dict(gap=GAP)),
    ("task_TAPAS", "task", dict(algorithm="TAPAS", gap=GAP)),
    ("task_LUCE", "task", dict(algorithm="LUCE", gap=GAP)),
    ("task_BFW", "task", dict(algorithm="BFW", gap=GAP)),
    ("latent_ol1", "latent_gp", dict(algorithm="ol1", gap=GAP,
                                     max_explicit=8, max_iter=3000)),
]


def main():
    outdir = ROOT / "results" / "stap_top5"
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for inst_name, cap in INSTANCES:
        inst = Instance.load(ROOT / "tapbench" / inst_name)
        print(f"== {inst_name}", flush=True)
        for arm, solver, kw in ARMS:
            try:
                mod = adapters.get(solver)
                out = mod.solve(inst, max_time=cap, **kw)
            except Exception as e:
                rows.append(dict(instance=inst_name, arm=arm, status="failed",
                                 error=str(e)[:120]))
                print(f"  {arm} FAILED: {e}", flush=True)
                continue
            s = out["summary"]
            lp = outdir / "tmp_lp.csv"
            with open(lp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["link_id", "from_node_id",
                                                  "to_node_id", "volume",
                                                  "travel_time"],
                                   extrasaction="ignore")
                w.writeheader()
                w.writerows(out["flows"])
            rep = verify(inst, lp, self_reported_gap=s.get("relative_gap"))
            lp.unlink()
            rows.append(dict(instance=inst_name, arm=arm, status="ok",
                             iterations=s.get("iterations"),
                             self_gap=s.get("relative_gap"),
                             recomputed_gap=rep["relative_gap_recomputed"],
                             time_s=s.get("wall_time_s"),
                             tstt=s.get("tstt") or rep["tstt_recomputed"],
                             certified=rep["certified"]))
            print(f"  {arm}: t={s.get('wall_time_s')}s "
                  f"gap={rep['relative_gap_recomputed']:.1e} "
                  f"certified={rep['certified']}", flush=True)

    keys = ["instance", "arm", "status", "iterations", "self_gap",
            "recomputed_gap", "time_s", "tstt", "certified", "error"]
    with open(outdir / "comparison.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    lines = ["# Top-5 STAP comparison (gap target 1e-5, all certified "
             "independently)", ""]
    for inst_name, _ in INSTANCES:
        lines += [f"## {inst_name}", "",
                  "| arm | time (s) | recomputed gap | TSTT | certified |",
                  "|---|---|---|---|---|"]
        for r in rows:
            if r["instance"] != inst_name:
                continue
            if r["status"] == "failed":
                lines.append(f"| {r['arm']} | FAILED | {r.get('error','')} | | |")
            else:
                lines.append(f"| {r['arm']} | {r['time_s']} | "
                             f"{r['recomputed_gap']:.2e} | "
                             f"{r['tstt']:,.0f} | {r['certified']} |")
        lines.append("")
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"-> {outdir}", flush=True)


if __name__ == "__main__":
    main()
