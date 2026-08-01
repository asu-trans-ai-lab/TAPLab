"""TAPValidate network statistics: everything is computed from the imported
instance, never hard-coded in documentation. `taplab stats <instance>` writes
network_statistics.json next to the console output."""
from __future__ import annotations

import json
from collections import defaultdict


def _dist(values):
    """min / quartiles / max / mean for a numeric column."""
    v = sorted(values)
    if not v:
        return None
    n = len(v)

    def q(p):
        i = p * (n - 1)
        lo = int(i)
        hi = min(lo + 1, n - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (i - lo), 6)

    return dict(min=round(v[0], 6), p25=q(0.25), median=q(0.5), p75=q(0.75),
                max=round(v[-1], 6), mean=round(sum(v) / n, 6))


def network_statistics(instance):
    cents = instance.centroids()          # zone_id -> node_id
    cent_nodes = set(cents.values())
    n_nodes = len(instance.nodes)
    n_cent = len(cent_nodes)

    connectors, invalid_conn, zero_cap = [], [], []
    fwd = defaultdict(list)
    fftt, caps, alphas, betas = [], [], [], []
    for r in instance.links:
        a, b = instance.link_key(r)
        fwd[a].append(b)
        touches = (a in cent_nodes) + (b in cent_nodes)
        declared = str(r.get("link_type", "")).strip() == "centroid_connector"
        if declared or touches == 1:
            connectors.append((a, b))
            if declared and touches != 1:
                invalid_conn.append((a, b))
        cap = float(r.get("capacity") or 0)
        if cap <= 0:
            zero_cap.append((a, b))
        else:
            caps.append(cap)
        fs = float(r.get("free_speed") or 30) or 30
        fftt.append(float(r.get("vdf_fftt") or 0)
                    or float(r["length"]) / fs * 60.0)
        alphas.append(float(r.get("vdf_alpha") or 0.15))
        betas.append(float(r.get("vdf_beta") or 4.0))

    # demand aggregates
    od = defaultdict(float)
    by_class = defaultdict(float)
    for r in instance.demand:
        v = float(r["volume"])
        if v <= 0:
            continue
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        od[(o, d)] += v
        key = f"{r.get('agent_type', 'auto') or 'auto'}/{r.get('period', '-') or '-'}"
        by_class[key] += v

    # OD coverage: BFS reachability from every origin centroid
    reach_cache = {}

    def reach(o):
        if o not in reach_cache:
            seen = {o}
            stack = [o]
            while stack:
                u = stack.pop()
                for w in fwd[u]:
                    if w not in seen:
                        seen.add(w)
                        stack.append(w)
            reach_cache[o] = seen
        return reach_cache[o]

    disconnected = [(o, d) for (o, d), v in od.items()
                    if o != d and (o not in cents or d not in cents
                                   or cents[d] not in reach(cents[o]))]

    n_links = len(instance.links)
    return {
        "physical_nodes": n_nodes - n_cent,
        "centroid_nodes": n_cent,
        "zones": len(cents),
        "links": n_links,
        "centroid_connectors": len(connectors),
        "invalid_connector_links": len(invalid_conn),
        "zero_or_missing_capacity_links": len(zero_cap),
        "positive_demand_od_pairs": len(od),
        "intrazonal_od_pairs": sum(1 for (o, d) in od if o == d),
        "total_demand": round(sum(od.values()), 2),
        "demand_by_class_period": {k: round(v, 2)
                                   for k, v in sorted(by_class.items())},
        "network_density_links_per_node": round(n_links / max(n_nodes, 1), 3),
        "disconnected_positive_demand_od_pairs": len(disconnected),
        "od_coverage": round(1.0 - len(disconnected) / max(len(od), 1), 6),
        "free_flow_time_min": _dist(fftt),
        "capacity": _dist(caps),
        "bpr_alpha": _dist(alphas),
        "bpr_beta": _dist(betas),
    }


def write_stats(instance, outpath=None):
    s = network_statistics(instance)
    out = outpath or (instance.path / "network_statistics.json")
    out.write_text(json.dumps(s, indent=1), encoding="utf-8")
    return s
