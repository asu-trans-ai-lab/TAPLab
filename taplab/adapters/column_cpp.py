"""TAPAdapter: the CompressedTAP C++ column engine (vendored as
cpp/column_solver.cpp, built to bin/column_solver.exe).

Fixed-pool algorithms on a penalty-KSP pool, per the TSL-paper protocol:

  algorithm="latent"  R1: anchor elimination + explicit majors + one
                      nonnegative atom per cohort  (the latent-atom engine)
  algorithm="full"    R0: full GP over all columns with elimination
                      (Jayakrishnan-style shifts)
  algorithm="decomp"  runs H0 (Bertsekas-style full-simplex projected
                      gradient) / R0 / R1 and reports the decomposition
                      identity S_R * S_C|R = S_RC — timing study only

The pool is generated on the fly (penalty-KSP, K per `pool_k`) and written
as a case directory; a restricted-pool solve is NOT a full-network UE claim
— the reported gap is the pool gap, and `taplab verify` recomputes the
full-network gap from the returned flows.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from ..ksp import generate_pool

ROOT = Path(__file__).resolve().parent.parent.parent


def _exe():
    exe = os.environ.get("TAPLAB_COLUMN_EXE") or str(ROOT / "bin" / "column_solver.exe")
    if not Path(exe).exists():
        raise RuntimeError("build bin/column_solver.exe (g++ -O2 -std=c++17 "
                           "-static -o bin/column_solver.exe cpp/column_solver.cpp)")
    return exe


def _write_case(instance, pool, work: Path):
    links = []
    link_index = {}
    for i, r in enumerate(instance.links):
        link_index[str(r.get("link_id", i + 1))] = i
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or (float(r["length"]) / fs * 60.0
                                                 if float(r.get("length") or 0) > 0 else 0.0)
        links.append((instance.link_key(r), fftt, float(r.get("capacity") or 1),
                      float(r.get("vdf_alpha") or 0.15),
                      float(r.get("vdf_beta") or 4.0)))
    with open(work / "resources.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["resource_id", "background", "t0", "capacity", "alpha",
                    "beta", "toll"])
        for i, (_, t0, cap, al, be) in enumerate(links):
            w.writerow([i, 0.0, f"{t0:.12g}", f"{cap:.12g}", al, be, 0.0])

    cents = instance.centroids()
    inv_c = {v: k for k, v in cents.items()}
    dem = defaultdict(float)
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d:
            dem[(o, d)] += v
    cohorts, coh_index = [], {}
    rows = []
    for (o, d, pid, link_ids, cost) in pool:
        key = (inv_c.get(o), inv_c.get(d))
        if key not in coh_index:
            coh_index[key] = len(cohorts)
            cohorts.append(key)
        seq = ";".join(str(link_index[x]) for x in link_ids.split(";"))
        cid = hashlib.sha1(f"{key}|{seq}".encode()).hexdigest()[:16]
        rows.append((cid, coh_index[key], seq))
    with open(work / "columns.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["column_id", "cohort_id", "resource_sequence"])
        w.writerows(rows)
    with open(work / "demand.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cohort_id", "origin", "destination", "desired_departure",
                    "demand"])
        for i, (o, d) in enumerate(cohorts):
            w.writerow([i, o, d, 0, f"{dem.get((o, d), 0.0):.6f}"])
    (work / "meta.json").write_text(json.dumps(dict(
        problem_type="static_path_pool", n_resources=len(links),
        n_columns=len(rows), n_cohorts=len(cohorts),
        generator="taplab penalty-KSP")))
    return links


def solve(instance, algorithm="latent", gap=1e-5, max_time=600,
          pool_k=32, penalty=1.5, major_share=0.75):
    exe = _exe()
    work = Path(tempfile.mkdtemp(prefix="taplab_colcpp_"))
    t0 = time.time()
    pool = generate_pool(instance, pool_k, penalty)
    t_pool = time.time() - t0
    links = _write_case(instance, pool, work)

    mode = {"latent": "latent", "full": "full", "decomp": "decomp"}[algorithm]
    flows_file = work / "flows.csv"
    cmd = [exe, str(work), "--mode", mode, "--repeats", "1",
           "--tol", f"{gap:g}", "--major-share", str(major_share)]
    if mode in ("latent", "full"):
        cmd += ["--flows-out", str(flows_file)]
    r = subprocess.run(cmd, capture_output=True, timeout=max_time + 120)
    stdout = (r.stdout or b"").decode("utf-8", "replace")

    flows = []
    if flows_file.exists():
        for row in csv.DictReader(open(flows_file)):
            i = int(row["resource_id"])
            (a, b), fftt, cap, al, be = links[i]
            v = float(row["flow"])
            tt = fftt * (1.0 + al * (v / cap) ** be) if cap > 0 else fftt
            flows.append(dict(link_id="", from_node_id=a, to_node_id=b,
                              volume=round(v, 4), travel_time=round(tt, 6)))
    stats = dict(re.findall(r"(\w+)=([^\s]+)", stdout))
    pool_gap = stats.get("latent_gap" if mode == "latent" else "full_gap")
    tstt = sum(f["volume"] * f["travel_time"] for f in flows) or None
    return dict(flows=flows, convergence=[],
                summary=dict(solver="column_cpp", algorithm=algorithm,
                             pool_k=pool_k, pool_paths=len(pool),
                             pool_gen_s=round(t_pool, 3),
                             relative_gap=float(pool_gap) if pool_gap else None,
                             gap_scope="pool (restricted master, NOT "
                                       "full-network; verify recomputes)",
                             tstt=round(tstt, 2) if tstt else None,
                             wall_time_s=round(time.time() - t0, 3),
                             engine_stdout=stdout.strip()[-400:],
                             workdir=str(work)))
