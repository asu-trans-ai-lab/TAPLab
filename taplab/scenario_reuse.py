"""B5 scenario-reuse experiment core: the paper-faithful fixed-atom model.

Semantics follow stable_release/paper2_latent_atom/code/pairwise_fw_atom.py
exactly:

  build_atom_model : per OD, anchor + up to maj_cap majors ranked by NOMINAL
                     path flow x0, plus ONE atom whose link weights are the
                     nominal minor-flow shares pi_i = x0_i / sum(x0_minor),
                     FIXED for the whole solve (no refold, no pricing)
  gp_solve         : Jayakrishnan GP on the OD simplex — shift every column
                     toward the cheapest, step = min(mass, gap / curvature),
                     curvature = sum t'_a coef_a^2 over the weighted
                     symmetric difference; Gauss-Seidel fresh costs per OD;
                     certificate = represented-column relative gap

The scenario-reuse protocol: solve the base instance ONCE on the full pool
(that solve supplies x0 and fixes the compressed footprints), then re-solve
demand/capacity scenarios in the compressed space, warm-started, against a
cold full-pool GP baseline per scenario.
"""
from __future__ import annotations

import time
from collections import defaultdict

import numpy as np


def build_pool_arrays(instance, pool):
    """CSR path-link incidence + BPR arrays from a penalty-KSP pool."""
    link_index = {}
    t0v, capv, alv, bev = [], [], [], []
    for i, r in enumerate(instance.links):
        link_index[str(r.get("link_id", i + 1))] = i
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or (float(r["length"]) / fs * 60.0
                                                 if float(r.get("length") or 0) > 0 else 0.0)
        t0v.append(fftt)
        capv.append(max(float(r.get("capacity") or 1), 1e-9))
        alv.append(float(r.get("vdf_alpha") or 0.15))
        bev.append(float(r.get("vdf_beta") or 4.0))

    cents = instance.centroids()
    inv_c = {v: k for k, v in cents.items()}
    dem = defaultdict(float)
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d:
            dem[(o, d)] += v

    ods, od_index = [], {}
    paths, p2od = [], []
    for (o, d, pid, link_ids, cost) in pool:
        key = (inv_c.get(o), inv_c.get(d))
        if key not in od_index:
            od_index[key] = len(ods)
            ods.append(key)
        paths.append(np.array([link_index[x] for x in link_ids.split(";")],
                              dtype=np.int64))
        p2od.append(od_index[key])
    return dict(paths=paths, p2od=np.array(p2od), n_od=len(ods),
                d=np.array([dem[k] for k in ods]),
                t0=np.array(t0v), cap=np.array(capv),
                alpha=np.array(alv), beta=np.array(bev),
                m=len(t0v), ods=ods)


def _bpr(P, v, dscale=1.0, cscale=1.0):
    cap = P["cap"] * cscale
    r = np.maximum(v, 0.0) / cap
    t = P["t0"] * (1.0 + P["alpha"] * r ** P["beta"])
    tp = np.where(P["beta"] != 1.0,
                  P["t0"] * P["alpha"] * P["beta"] / cap * r ** (P["beta"] - 1.0),
                  P["t0"] * P["alpha"] / cap)
    return t, tp


def beckmann(P, v, cscale=1.0):
    cap = P["cap"] * cscale
    r = np.maximum(v, 0.0) / cap
    return float(np.sum(P["t0"] * v + P["t0"] * P["alpha"] * cap
                        / (P["beta"] + 1.0) * r ** (P["beta"] + 1.0)))


def full_model(P):
    """Every pooled path is an explicit column."""
    groups = defaultdict(list)
    for p, w in enumerate(P["p2od"]):
        groups[int(w)].append(p)
    cols = []
    for w in range(P["n_od"]):
        cols.append([dict(foot=[(P["paths"][p], 1.0)], mass=0.0)
                     for p in groups[w]])
    return cols


def atom_model(P, x0, maj_cap=6):
    """Paper-faithful: anchor + maj_cap majors by nominal flow + one fixed
    atom of nominal minor shares."""
    groups = defaultdict(list)
    for p, w in enumerate(P["p2od"]):
        groups[int(w)].append(p)
    cols = []
    for w in range(P["n_od"]):
        g = np.array(groups[w])
        order = g[np.argsort(-x0[g])] if x0[g].sum() > 0 else g
        keep = order[:1 + maj_cap]
        minors = order[1 + maj_cap:]
        od_cols = [dict(foot=[(P["paths"][p], 1.0)], mass=0.0) for p in keep]
        if len(minors):
            xm = np.maximum(x0[minors], 1e-12)
            pi = xm / xm.sum()
            od_cols.append(dict(foot=[(P["paths"][minors[i]], float(pi[i]))
                                      for i in range(len(minors))], mass=0.0))
        cols.append(od_cols)
    return cols


def _foot_cost(foot, t):
    return sum(c * t[a].sum() for a, c in foot)


def gp_solve(P, cols, dscale=1.0, cscale=1.0, tol=1e-6, max_it=500,
             warm=False):
    """Jayakrishnan GP on the column model; returns link flows v, gap,
    iterations, time, and per-column masses (for warm starts)."""
    d = P["d"] * dscale
    m = P["m"]
    v = np.zeros(m)
    if warm:
        for w, od in enumerate(cols):
            tot = sum(c["mass"] for c in od)
            for c in od:
                c["mass"] = c["mass"] / tot * d[w] if tot > 0 else 0.0
                for a, cf in c["foot"]:
                    v[a] += c["mass"] * cf
        for w, od in enumerate(cols):
            if not any(c["mass"] > 0 for c in od) and d[w] > 0:
                od[0]["mass"] = d[w]
                for a, cf in od[0]["foot"]:
                    v[a] += d[w] * cf
    else:
        t0ff, _ = _bpr(P, np.zeros(m), dscale, cscale)
        for w, od in enumerate(cols):
            for c in od:
                c["mass"] = 0.0
            cheap = int(np.argmin([_foot_cost(c["foot"], t0ff) for c in od]))
            od[cheap]["mass"] = d[w]
            for a, cf in od[cheap]["foot"]:
                v[a] += d[w] * cf

    t_start = time.time()
    gap = np.inf
    for it in range(1, max_it + 1):
        for w, od in enumerate(cols):
            if len(od) < 2 or d[w] <= 0:
                continue
            t, tp = _bpr(P, v, dscale, cscale)
            costs = [_foot_cost(c["foot"], t) for c in od]
            s = int(np.argmin(costs))
            for i, c in enumerate(od):
                if i == s or c["mass"] <= 1e-12:
                    continue
                g = costs[i] - costs[s]
                if g <= 1e-12:
                    continue
                dv = defaultdict(float)
                for a, cf in c["foot"]:
                    for aa in a:
                        dv[aa] += cf
                for a, cf in od[s]["foot"]:
                    for aa in a:
                        dv[aa] -= cf
                arr = np.fromiter(dv.keys(), dtype=np.int64)
                coef = np.fromiter(dv.values(), dtype=float)
                h = float((tp[arr] * coef * coef).sum())
                step = min(c["mass"], g / max(h, 1e-12))
                for a, cf in c["foot"]:
                    v[a] -= step * cf
                for a, cf in od[s]["foot"]:
                    v[a] += step * cf
                c["mass"] -= step
                od[s]["mass"] += step
        t, _ = _bpr(P, v, dscale, cscale)
        cx = cy = 0.0
        for w, od in enumerate(cols):
            costs = [_foot_cost(c["foot"], t) for c in od]
            cx += sum(c["mass"] * costs[i] for i, c in enumerate(od))
            cy += d[w] * min(costs)
        gap = (cx - cy) / max(cy, 1e-12)
        if gap < tol:
            break
    return dict(v=v, gap=float(gap), iterations=it,
                time_s=round(time.time() - t_start, 4),
                obj=beckmann(P, v, cscale))
