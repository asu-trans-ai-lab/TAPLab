"""Independent solution validator (TAPValidate level 3).

`taplab verify <instance> --solver <name>` recomputes, WITHOUT trusting the
solver: link costs from the instance's BPR parameters, the Beckmann
objective, total system travel time, the all-or-nothing shortest-path lower
bound, and the relative gap; and checks negative / NaN / missing flows and
flow conservation (net outflow at every node against the OD table). The
certification is written to validation_report.json beside the run outputs.
"""
from __future__ import annotations

import csv
import heapq
import json
import math
from collections import defaultdict


def verify(instance, lp_path, gap_target=None, self_reported_gap=None):
    cents = instance.centroids()
    cent_nodes = set(cents.values())

    links, index = [], {}
    for r in instance.links:
        a, b = instance.link_key(r)
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or (float(r["length"]) / fs * 60.0
                                                 if float(r.get("length") or 0) > 0 else 0.0)
        links.append(dict(a=a, b=b, cap=float(r.get("capacity") or 0),
                          fftt=fftt, B=float(r.get("vdf_alpha") or 0.15),
                          P=float(r.get("vdf_beta") or 4.0)))
        index[(a, b)] = len(links) - 1

    x = [0.0] * len(links)
    issues = []
    n_rows = 0
    for row in csv.DictReader(open(lp_path, encoding="utf-8-sig")):
        n_rows += 1
        try:
            k = (int(float(row["from_node_id"])), int(float(row["to_node_id"])))
            v = float(row["volume"])
        except (ValueError, KeyError):
            issues.append(f"unparseable row {n_rows}")
            continue
        if math.isnan(v):
            issues.append(f"NaN flow on {k}")
            continue
        if v < -1e-6:
            issues.append(f"negative flow {v} on {k}")
        if k not in index:
            issues.append(f"flow on unknown link {k}")
            continue
        x[index[k]] += v
    missing = sum(1 for i, l in enumerate(links) if x[i] == 0.0)

    # recomputed costs, TSTT, Beckmann objective
    t = []
    tstt = beck = 0.0
    for i, l in enumerate(links):
        if l["cap"] > 0:
            r = x[i] / l["cap"]
            ti = l["fftt"] * (1.0 + l["B"] * r ** l["P"])
            beck += l["fftt"] * x[i] + l["fftt"] * l["B"] * l["cap"] \
                / (l["P"] + 1.0) * r ** (l["P"] + 1.0)
        else:
            ti = l["fftt"]
            beck += l["fftt"] * x[i]
        t.append(ti)
        tstt += ti * x[i]

    # flow conservation: net outflow at each node must equal the node's net
    # OD supply (origins positive, destinations negative, zero elsewhere)
    net = defaultdict(float)
    for i, l in enumerate(links):
        net[l["a"]] += x[i]
        net[l["b"]] -= x[i]
    supply = defaultdict(float)
    tot_demand = 0.0
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d and o in cents and d in cents:
            supply[cents[o]] += v
            supply[cents[d]] -= v
            tot_demand += v
    cons_err = max((abs(net[n] - supply[n])
                    for n in set(net) | set(supply)), default=0.0)

    # shortest-path lower bound on recomputed costs (centroids blocked)
    fwd = defaultdict(list)
    for i, l in enumerate(links):
        fwd[l["a"]].append((l["b"], i))
    block = len(cent_nodes) < len(set(net) | cent_nodes)
    demand_by_o = defaultdict(list)
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o != d and o in cents and d in cents:
            demand_by_o[cents[o]].append((cents[d], v))
    sptt = 0.0
    unreachable = 0
    for o, dests in demand_by_o.items():
        dist = {o: 0.0}
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
                    heapq.heappush(pq, (nd, v))
        for d, vol in dests:
            if d in dist:
                sptt += dist[d] * vol
            else:
                unreachable += 1
    rgap = (tstt - sptt) / max(sptt, 1e-9) if sptt > 0 else None

    report = dict(
        rows_read=n_rows, instance_links=len(links),
        links_without_flow=missing,
        issues=issues[:50], issue_count=len(issues),
        total_demand=round(tot_demand, 2),
        max_conservation_error=round(cons_err, 6),
        conservation_error_share=round(cons_err / max(tot_demand, 1e-9), 8),
        tstt_recomputed=round(tstt, 2),
        beckmann_objective=round(beck, 2),
        sptt_lower_bound=round(sptt, 2),
        relative_gap_recomputed=rgap,
        unreachable_od_pairs=unreachable,
    )
    ok = (not issues and cons_err <= max(1e-3 * tot_demand, 1.0)
          and unreachable == 0)
    if gap_target is not None and rgap is not None:
        report["gap_target"] = gap_target
        report["meets_gap_target"] = rgap <= gap_target
        ok = ok and rgap <= gap_target
    if self_reported_gap is not None and rgap is not None:
        # a solver's claim must survive independent recomputation: allow an
        # order of magnitude of definitional slack, no more
        consistent = rgap <= max(10.0 * self_reported_gap,
                                 self_reported_gap + 1e-6)
        report["self_reported_gap"] = self_reported_gap
        report["gap_consistent_with_self_report"] = consistent
        ok = ok and consistent
    report["certified"] = ok
    return report
