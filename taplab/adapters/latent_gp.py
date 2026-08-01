"""TAPAdapter: path-based Gradient Projection with latent-atom compression.

A native TAPLab port of the origin_bush_latent research line (P0 explicit-path
GP and the OL1 latent-atom method), generalized from the controlled monotone
grid to arbitrary instances via adaptive column generation:

  P0  (algorithm="p0")     explicit path columns only; new columns are priced
                           in against network shortest paths each iteration
  OL1 (algorithm="ol1")    when an OD pair's pool exceeds `max_explicit`
                           columns, its smallest-flow columns fold into ONE
                           nonnegative latent atom: a fixed flow-weighted
                           link-incidence vector that keeps competing in the
                           GP shifts at cost = incidence . t, but is never
                           re-expanded. Compression is refreshed whenever the
                           pool overflows again.

Column shifts use the diagonal-Newton GP step (cost difference over the sum
of BPR derivatives on the symmetric difference of the two columns). The
reported relative gap is the true network gap priced against shortest paths —
a small restricted-master gap alone never certifies pool adequacy.

Pure Python; intended for diagnostic-to-intermediate instances. Reported
work counters: shortest-path calls, columns generated, columns folded.
"""
from __future__ import annotations

import heapq
import time
from collections import defaultdict


def solve(instance, algorithm="ol1", gap=1e-6, max_time=600, max_iter=200,
          max_explicit=4):
    t0 = time.time()
    cents = instance.centroids()
    cent_nodes = set(cents.values())

    links = []
    fwd = defaultdict(list)
    for r in instance.links:
        a, b = instance.link_key(r)
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or (float(r["length"]) / fs * 60.0
                                                 if float(r.get("length") or 0) > 0 else 0.0)
        links.append(dict(a=a, b=b, cap=float(r.get("capacity") or 0),
                          fftt=fftt, B=float(r.get("vdf_alpha") or 0.15),
                          P=float(r.get("vdf_beta") or 4.0),
                          lid=r.get("link_id", "")))
        fwd[a].append((b, len(links) - 1))
    m = len(links)
    all_nodes = set(fwd) | {l["b"] for l in links}
    block = len(cent_nodes) < len(all_nodes)

    od = defaultdict(float)
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d and o in cents and d in cents:
            od[(cents[o], cents[d])] += v
    by_origin = defaultdict(list)
    for (o, d), v in od.items():
        by_origin[o].append(d)

    x = [0.0] * m           # link flows
    t = [0.0] * m           # link times
    dt = [0.0] * m          # BPR derivatives

    def _refresh(i):
        l = links[i]
        if l["cap"] > 0:
            r_ = max(x[i], 0.0) / l["cap"]
            t[i] = l["fftt"] * (1.0 + l["B"] * r_ ** l["P"])
            dt[i] = l["fftt"] * l["B"] * l["P"] / l["cap"] \
                * (r_ ** (l["P"] - 1.0) if l["P"] != 1.0 else 1.0)
        else:
            t[i] = l["fftt"]
            dt[i] = 0.0

    def update_times():
        for i in range(m):
            _refresh(i)

    sp_calls = 0

    def sp_tree(o):
        nonlocal sp_calls
        sp_calls += 1
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
                nd = du + t[li]
                if nd < dist.get(v, 1e18) - 1e-12:
                    dist[v] = nd
                    prev[v] = li
                    heapq.heappush(pq, (nd, v))
        return dist, prev

    def path_of(prev, o, d):
        p = []
        u = d
        while u != o:
            li = prev.get(u)
            if li is None:
                return None
            p.append(li)
            u = links[li]["a"]
        return tuple(reversed(p))

    # column pools: pools[(o,d)] = {"cols": {path: flow}, "atom": [inc, flow]}
    # atom incidence is a dict {link_index: weight}
    pools = {}
    generated = folded = 0

    update_times()
    for o, dests in by_origin.items():
        dist, prev = sp_tree(o)
        for d in dests:
            p = path_of(prev, o, d)
            if p is None:
                continue
            pools[(o, d)] = {"cols": {p: od[(o, d)]}, "atom": None}
            for li in p:
                x[li] += od[(o, d)]

    def col_cost(path):
        return sum(t[li] for li in path)

    def atom_cost(inc):
        return sum(w * t[li] for li, w in inc.items())

    def shift(inc_from, inc_to, amount):
        """Move `amount` of flow between two incidence structures."""
        for li, w in inc_from.items():
            x[li] -= amount * w
        for li, w in inc_to.items():
            x[li] += amount * w

    history = []
    rgap = None
    latent = (algorithm.lower() == "ol1")
    for it in range(1, max_iter + 1):
        update_times()
        # network pricing + gap in one sweep
        tstt = sum(t[i] * x[i] for i in range(m))
        sptt = 0.0
        for o, dests in by_origin.items():
            dist, prev = sp_tree(o)
            for d in dests:
                key = (o, d)
                if key not in pools:
                    continue
                sptt += dist.get(d, 0.0) * od[key]
                p = path_of(prev, o, d)
                if p is not None and p not in pools[key]["cols"]:
                    best = min((col_cost(q) for q in pools[key]["cols"]),
                               default=1e18)
                    if dist[d] < best - 1e-9:
                        pools[key]["cols"][p] = 0.0
                        generated += 1
        rgap = (tstt - sptt) / max(sptt, 1e-9)
        history.append((it, rgap, round(time.time() - t0, 3)))
        if rgap < gap or time.time() - t0 > max_time:
            break

        # Gauss-Seidel GP shifts per OD: refresh the OD's own link costs and
        # derivatives first (earlier ODs' shifts already moved flow), then
        # diagonal Newton on the symmetric difference, bounded by the
        # column's flow. The guarded denominator prevents full-pool slams
        # when the BPR curve is locally flat.
        for key, pool in pools.items():
            entries = [[dict.fromkeys(p, 1.0), f, p]
                       for p, f in pool["cols"].items()]
            if pool["atom"] is not None:
                entries.append([pool["atom"][0], pool["atom"][1], None])
            if len(entries) < 2:
                continue
            touched = set()
            for e in entries:
                touched |= set(e[0])
            for li in touched:
                _refresh(li)
            costs = [atom_cost(e[0]) for e in entries]
            bi = min(range(len(entries)), key=lambda i: costs[i])
            for i, e in enumerate(entries):
                if i == bi or e[1] <= 1e-12:
                    continue
                diff = costs[i] - costs[bi]
                if diff <= 1e-12:
                    continue
                keys = set(e[0]) | set(entries[bi][0])
                h = sum(dt[li] * (e[0].get(li, 0) - entries[bi][0].get(li, 0)) ** 2
                        for li in keys)
                hmin = 1e-3 * diff / max(e[1], 1e-12)   # cap step at 1000x flow-scale
                step = min(e[1], diff / max(h, hmin))
                shift(e[0], entries[bi][0], step)
                for li in keys:
                    _refresh(li)
                costs[bi] = atom_cost(entries[bi][0])
                e[1] -= step
                entries[bi][1] += step
            # write back + latent compression
            new_cols = {}
            atom = pool["atom"]
            for e in entries:
                if e[2] is not None:
                    if e[1] > 1e-12:
                        new_cols[e[2]] = e[1]
                else:
                    atom = [e[0], e[1]]
            if latent and len(new_cols) > max_explicit:
                ranked = sorted(new_cols.items(), key=lambda kv: -kv[1])
                keep = dict(ranked[:max_explicit])
                minor = ranked[max_explicit:]
                tot = sum(f for _, f in minor) + (atom[1] if atom else 0.0)
                if tot > 1e-12:
                    inc = defaultdict(float)
                    if atom:
                        for li, w in atom[0].items():
                            inc[li] += w * atom[1]
                    for p, f in minor:
                        folded += 1
                        for li in p:
                            inc[li] += f
                    atom = [{li: w / tot for li, w in inc.items()}, tot]
                new_cols = keep
            pool["cols"] = new_cols
            pool["atom"] = atom if atom and atom[1] > 1e-12 else \
                (atom if not latent else atom)

    update_times()
    flows = [dict(link_id=l["lid"], from_node_id=l["a"], to_node_id=l["b"],
                  volume=round(x[i], 4), travel_time=round(t[i], 6))
             for i, l in enumerate(links)]
    n_cols = sum(len(p["cols"]) for p in pools.values())
    n_atoms = sum(1 for p in pools.values() if p["atom"])
    return dict(flows=flows, convergence=history,
                summary=dict(solver="latent_gp", algorithm=algorithm.lower(),
                             iterations=history[-1][0] if history else 0,
                             relative_gap=rgap,
                             wall_time_s=round(time.time() - t0, 3),
                             tstt=round(sum(t[i] * x[i] for i in range(m)), 2),
                             shortest_path_calls=sp_calls,
                             columns_active=n_cols,
                             columns_generated=generated,
                             columns_folded=folded,
                             latent_atoms=n_atoms))
