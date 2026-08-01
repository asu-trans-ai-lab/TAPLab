"""Compact binary path-pool storage (the CompressedTAP cpp_problem format).

Large K pools stored as CSV are bulky; the CompressedTAP experiments store
them as raw CSR arrays, which the C++ engines (column_solver, pairwise_fw,
logit_sue) mmap directly:

    B_indptr.i64    path -> [start, end) into B_indices     (n_paths + 1)
    B_indices.i32   link indices (0-based row of link.csv)  (nnz)
    p2od.i32        path -> cohort/OD index                 (n_paths)
    dvec.f64        demand per cohort                       (n_cohorts)
    bpr_t0.f64 / bpr_cap.f64 / bpr_alpha.f64 / bpr_beta.f64 (n_links)
    meta.json       dimensions + provenance + od table

The high-K strategy follows the TSL paper: pools can be generated
aggressively (K = 32-64 per OD) because minor paths never become explicit
decision variables — the major/minor split plus a low-rank minor basis keeps
the optimizer at s + r variables regardless of pool size.

    taplab pool <instance> --k 32           -> optional/cpp_problem/
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

from .ksp import generate_pool


def write_binary_pool(instance, k=32, penalty=1.5, outdir=None):
    out = Path(outdir) if outdir else instance.path / "optional" / "cpp_problem"
    out.mkdir(parents=True, exist_ok=True)

    link_index = {}
    t0v, capv, alv, bev = [], [], [], []
    for i, r in enumerate(instance.links):
        lid = str(r.get("link_id", i + 1))
        link_index[lid] = i
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or (float(r["length"]) / fs * 60.0
                                                 if float(r.get("length") or 0) > 0 else 0.0)
        t0v.append(fftt)
        capv.append(float(r.get("capacity") or 1))
        alv.append(float(r.get("vdf_alpha") or 0.15))
        bev.append(float(r.get("vdf_beta") or 4.0))

    pool = generate_pool(instance, k, penalty)

    ods, od_index = [], {}
    from collections import defaultdict
    dem = defaultdict(float)
    cents = instance.centroids()
    inv_c = {v: kz for kz, v in cents.items()}
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d:
            dem[(o, d)] += v

    indptr = [0]
    indices = []
    p2od = []
    for (o, d, pid, link_ids, cost) in pool:
        oz, dz = inv_c.get(o), inv_c.get(d)
        key = (oz, dz)
        if key not in od_index:
            od_index[key] = len(ods)
            ods.append(key)
        for lid in link_ids.split(";"):
            indices.append(link_index[lid])
        indptr.append(len(indices))
        p2od.append(od_index[key])
    dvec = [dem.get(key, 0.0) for key in ods]

    def dump(name, fmt, vals):
        with open(out / name, "wb") as f:
            f.write(struct.pack(f"<{len(vals)}{fmt}", *vals))

    dump("B_indptr.i64", "q", indptr)
    dump("B_indices.i32", "i", indices)
    dump("p2od.i32", "i", p2od)
    dump("dvec.f64", "d", dvec)
    dump("bpr_t0.f64", "d", t0v)
    dump("bpr_cap.f64", "d", capv)
    dump("bpr_alpha.f64", "d", alv)
    dump("bpr_beta.f64", "d", bev)
    (out / "meta.json").write_text(json.dumps(dict(
        format="cpp_problem (CompressedTAP CSR pool)",
        n_links=len(t0v), n_paths=len(p2od), n_cohorts=len(dvec),
        nnz=len(indices), k_requested=k, penalty=penalty,
        generator="taplab penalty-KSP",
        ods=[[int(o), int(d)] for o, d in ods]), indent=1))
    csv_bytes = sum(len(r[3]) + 30 for r in pool)
    bin_bytes = sum((out / n).stat().st_size for n in
                    ("B_indptr.i64", "B_indices.i32", "p2od.i32", "dvec.f64"))
    print(f"pool: {len(p2od):,} paths, {len(dvec):,} ODs, "
          f"K/OD {len(p2od)/max(len(dvec),1):.2f}, nnz {len(indices):,}; "
          f"binary {bin_bytes/1e6:.2f} MB vs ~{csv_bytes/1e6:.2f} MB CSV "
          f"-> {out}")
    return out
