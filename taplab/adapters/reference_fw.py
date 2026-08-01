"""Built-in pure-Python Frank-Wolfe reference solver (the reproducibility
anchor). Zero dependencies: Dijkstra + BPR + exact bisection line search.

Small/medium instances only (Sioux Falls in ~a second); larger networks
should use the native adapters. Returns normalized link flows plus the
convergence history.
"""
from __future__ import annotations

import heapq
import time
from collections import defaultdict


def solve(instance, algorithm="fw", gap=1e-6, max_time=300, max_iter=2000):
    cents = instance.centroids()
    links = []
    for r in instance.links:
        a, b = instance.link_key(r)
        cap = float(r["capacity"]) * (float(r.get("lanes") or 1) or 1) \
            if str(instance.settings.get("cap_per_lane", "no")).lower() in ("yes", "true", "1") \
            else float(r["capacity"])
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or float(r["length"]) / fs * 60.0
        B = float(r.get("vdf_alpha") or 0.15)
        P = float(r.get("vdf_beta") or 4.0)
        links.append(dict(a=a, b=b, cap=cap, fftt=fftt, B=B, P=P))
    m = len(links)
    fwd = defaultdict(list)
    for i, l in enumerate(links):
        fwd[l["a"]].append((l["b"], i))

    demand = defaultdict(list)   # origin node -> [(dest node, veh)]
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d and o in cents and d in cents:
            demand[cents[o]].append((cents[d], v))

    def times(x):
        return [l["fftt"] * (1.0 + l["B"] * (x[i] / l["cap"]) ** l["P"])
                for i, l in enumerate(links)]

    def aon(t):
        """All-or-nothing loading on current times."""
        y = [0.0] * m
        for o, dests in demand.items():
            dist = {o: 0.0}
            prev = {}
            pq = [(0.0, o)]
            while pq:
                du, u = heapq.heappop(pq)
                if du > dist.get(u, 1e18):
                    continue
                for v, li in fwd[u]:
                    nd = du + t[li]
                    if nd < dist.get(v, 1e18) - 1e-12:
                        dist[v] = nd
                        prev[v] = li
                        heapq.heappush(pq, (nd, v))
            for d, vol in dests:
                u = d
                while u != o:
                    li = prev.get(u)
                    if li is None:
                        break
                    y[li] += vol
                    u = links[li]["a"]
        return y

    def beckmann_grad(x, y, lam):
        """d/dlam of Beckmann along x + lam (y - x)."""
        g = 0.0
        for i, l in enumerate(links):
            z = x[i] + lam * (y[i] - x[i])
            ti = l["fftt"] * (1.0 + l["B"] * (z / l["cap"]) ** l["P"])
            g += ti * (y[i] - x[i])
        return g

    t0 = time.time()
    x = aon(times([0.0] * m))
    history = []
    for it in range(1, max_iter + 1):
        t = times(x)
        y = aon(t)
        # relative gap
        tstt = sum(t[i] * x[i] for i in range(m))
        sptt = sum(t[i] * y[i] for i in range(m))
        rgap = (tstt - sptt) / max(sptt, 1e-9)
        history.append((it, rgap, time.time() - t0))
        if rgap < gap or (time.time() - t0) > max_time:
            break
        # exact line search by bisection on the directional derivative
        lo, hi = 0.0, 1.0
        for _ in range(48):
            mid = 0.5 * (lo + hi)
            if beckmann_grad(x, y, mid) > 0:
                hi = mid
            else:
                lo = mid
        lam = 0.5 * (lo + hi)
        x = [x[i] + lam * (y[i] - x[i]) for i in range(m)]

    t = times(x)
    flows = [dict(from_node_id=l["a"], to_node_id=l["b"],
                  volume=round(x[i], 4), travel_time=round(t[i], 6))
             for i, l in enumerate(links)]
    return dict(flows=flows, convergence=history,
                summary=dict(solver="reference_fw", algorithm="fw",
                             iterations=history[-1][0] if history else 0,
                             relative_gap=history[-1][1] if history else None,
                             wall_time_s=round(time.time() - t0, 3),
                             tstt=round(sum(t[i] * x[i] for i in range(m)), 2)))
