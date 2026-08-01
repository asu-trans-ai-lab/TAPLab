"""Canonical K-shortest-path pool generation: deterministic penalty-KSP.

This is the generator validated by the OR-paper generator-axis study
(GEN-KSP): per OD, find the free-flow shortest path, multiply the costs of
its links by `penalty`, and re-price — repeated `k`-1 times. Link penalties
give route diversity directly (naive Yen returns many nearly identical
routes), deduplication is by link sequence, and the whole procedure is
deterministic: no seed needed.

  taplab ksp <instance> --k 8            -> optional/path_pool.csv

The pool file (o_zone_id, d_zone_id, path_id, link_ids, fftt_cost) feeds
fixed-pool experiments (track B3) and the latent-atom common-pool protocol.
"""
from __future__ import annotations

import csv
import heapq
from collections import defaultdict
from pathlib import Path


def generate_pool(instance, k=8, penalty=1.5):
    cents = instance.centroids()
    cent_nodes = set(cents.values())
    links = []
    fwd = defaultdict(list)
    for r in instance.links:
        a, b = instance.link_key(r)
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or (float(r["length"]) / fs * 60.0
                                                 if float(r.get("length") or 0) > 0 else 0.0)
        links.append((a, b, fftt, r.get("link_id", str(len(links) + 1))))
        fwd[a].append((b, len(links) - 1))
    block = len(cent_nodes) < len(set(fwd) | {l[1] for l in links})

    od = defaultdict(float)
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d and o in cents and d in cents:
            od[(cents[o], cents[d])] += v
    by_o = defaultdict(list)
    for (o, d) in od:
        by_o[o].append(d)

    def sp(o, cost):
        dist = {o: 0.0}
        prev = {}
        pq = [(0.0, o)]
        while pq:
            du, u = heapq.heappop(pq)
            if du > dist.get(u, 1e18):
                continue
            if block and u != o and u in cent_nodes:
                continue
            for v, li in fwd[u]:
                nd = du + cost[li]
                if nd < dist.get(v, 1e18) - 1e-12:
                    dist[v] = nd
                    prev[v] = li
                    heapq.heappush(pq, (nd, v))
        return dist, prev

    def path_of(prev, o, d):
        p, u = [], d
        while u != o:
            li = prev.get(u)
            if li is None:
                return None
            p.append(li)
            u = links[li][0]
        return tuple(reversed(p))

    base = [l[2] for l in links]
    pool = []
    for o, dests in by_o.items():
        found = {d: set() for d in dests}
        cost = list(base)
        for _round in range(k):
            dist, prev = sp(o, cost)
            touched = set()
            for d in dests:
                p = path_of(prev, o, d)
                if p is not None and p not in found[d] and len(found[d]) < k:
                    found[d].add(p)
                    touched.update(p)
            if not touched:
                break
            for li in touched:
                cost[li] *= penalty
        for d in dests:
            for i, p in enumerate(sorted(found[d],
                                         key=lambda q: sum(base[x] for x in q))):
                pool.append((o, d, i + 1,
                             ";".join(links[x][3] for x in p),
                             round(sum(base[x] for x in p), 6)))
    return pool


def write_pool(instance, k=8, penalty=1.5, outpath=None):
    pool = generate_pool(instance, k, penalty)
    out = outpath or (instance.path / "optional" / "path_pool.csv")
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["o_zone_id", "d_zone_id", "path_id", "link_ids",
                    "fftt_cost"])
        w.writerows(pool)
    n_od = len({(p[0], p[1]) for p in pool})
    print(f"pool: {len(pool):,} paths, {n_od:,} ODs, "
          f"K/OD {len(pool)/max(n_od,1):.2f} -> {out}")
    return pool
