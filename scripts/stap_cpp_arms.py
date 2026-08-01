"""C++ fixed-pool arms for the top-7 STAP comparison.

Adds, on the same instance ladder as stap_top5_comparison.py:

  colcpp_full     Jayakrishnan-style full GP over a K=32 penalty-KSP pool
                  (CompressedTAP C++ engine, anchor elimination)
  colcpp_latent   latent-atom engine: explicit majors + one atom per OD
  decomp row      H0 Bertsekas-style projected gradient / R0 / R1 timing
                  decomposition with the identity S_R * S_C|R = S_RC

Both flow-producing arms are re-verified on the FULL network — a
restricted-pool gap is never reported as a full-network claim.
Writes results/stap_top5/cpp_arms.csv (merged later into the top-7 report).
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taplab.instance import Instance          # noqa: E402
from taplab.adapters import column_cpp        # noqa: E402
from taplab.verify import verify              # noqa: E402

GAP = 1e-5
POOL_K = 32
INSTANCES = [
    ("forge/ladder_grid5", 120), ("forge/ladder_grid10", 200),
    ("forge/ladder_grid20", 400), ("forge/ladder_grid40", 600),
    ("forge/sts5x20_s1", 300), ("forge/sts8x30_s1", 600),
    ("sioux_falls", 120), ("chicago_sketch", 600),
]


def main():
    outdir = ROOT / "results" / "stap_top5"
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for inst_name, cap in INSTANCES:
        inst = Instance.load(ROOT / "tapbench" / inst_name)
        print(f"== {inst_name}", flush=True)
        for alg in ("full", "latent"):
            try:
                out = column_cpp.solve(inst, algorithm=alg, gap=GAP,
                                       max_time=cap, pool_k=POOL_K)
            except Exception as e:
                rows.append(dict(instance=inst_name, arm=f"colcpp_{alg}",
                                 status="failed", error=str(e)[:120]))
                print(f"  colcpp_{alg} FAILED: {e}", flush=True)
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
            rep = verify(inst, lp)
            lp.unlink()
            rows.append(dict(instance=inst_name, arm=f"colcpp_{alg}",
                             status="ok", pool_paths=s["pool_paths"],
                             pool_gen_s=s["pool_gen_s"],
                             pool_gap=s["relative_gap"],
                             fullnet_gap=rep["relative_gap_recomputed"],
                             time_s=s["wall_time_s"],
                             tstt=s.get("tstt"),
                             conservation_ok=rep["max_conservation_error"] < 1.0))
            print(f"  colcpp_{alg}: t={s['wall_time_s']}s pool_gap="
                  f"{s['relative_gap']:.1e} fullnet_gap="
                  f"{rep['relative_gap_recomputed']:.2e}", flush=True)
        try:
            out = column_cpp.solve(inst, algorithm="decomp", gap=GAP,
                                   max_time=cap, pool_k=POOL_K)
            rows.append(dict(instance=inst_name, arm="decomp_H0_R0_R1",
                             status="ok",
                             engine=out["summary"]["engine_stdout"][-320:]))
            print(f"  decomp: {out['summary']['engine_stdout'][-200:]}",
                  flush=True)
        except Exception as e:
            rows.append(dict(instance=inst_name, arm="decomp_H0_R0_R1",
                             status="failed", error=str(e)[:120]))
    keys = ["instance", "arm", "status", "pool_paths", "pool_gen_s",
            "pool_gap", "fullnet_gap", "time_s", "tstt", "conservation_ok",
            "engine", "error"]
    with open(outdir / "cpp_arms.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"-> {outdir / 'cpp_arms.csv'}", flush=True)


if __name__ == "__main__":
    main()
