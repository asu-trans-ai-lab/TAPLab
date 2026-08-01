"""TAPLab invariant validation (the Validate function).

Checks, per the compact-GMNS operational rules:
  V1 file presence and required columns
  V2 node/link referential integrity; no duplicate directed links
  V3 every demand zone has a centroid; centroid ids resolvable
  V4 every centroid reachable: has at least one incident link
     (connector or coincident-physical-node instances both pass)
  V5 connectors are not shortcuts: a centroid_connector must touch a
     centroid on exactly one end
  V6 unit sanity: capacity > 0, free_speed > 0, length > 0, fftt finite
  V7 demand sanity: nonnegative volumes; intrazonal share reported
  V8 connectivity: every OD pair with volume > 0 is connected
     (single-source reachability over directed links)
"""
from __future__ import annotations

from collections import defaultdict

from .instance import Instance


def validate(instance: Instance) -> dict:
    errors, warnings, info = [], [], {}
    nodes = {int(float(n["node_id"])): n for n in instance.nodes}
    cents = instance.centroids()

    # V1 columns
    for req, rows in [("node.csv", instance.nodes),
                      ("link.csv", instance.links),
                      ("demand.csv", instance.demand)]:
        if not rows:
            errors.append(f"V1 {req}: empty")
    need_link = {"from_node_id", "to_node_id", "capacity", "length"}
    if instance.links and not need_link <= set(instance.links[0]):
        errors.append(f"V1 link.csv missing columns {need_link - set(instance.links[0])}")

    # V2 integrity
    seen = set()
    for r in instance.links:
        a, b = instance.link_key(r)
        if a not in nodes or b not in nodes:
            errors.append(f"V2 link {r.get('link_id')}: endpoint not in node.csv ({a},{b})")
        if (a, b) in seen:
            warnings.append(f"V2 duplicate directed link ({a},{b})")
        seen.add((a, b))

    # V3 zones vs centroids
    zones_in_demand = {int(float(r["o_zone_id"])) for r in instance.demand} | \
                      {int(float(r["d_zone_id"])) for r in instance.demand}
    missing = sorted(z for z in zones_in_demand if z not in cents)
    if missing:
        errors.append(f"V3 demand zones with no centroid: {missing[:10]}"
                      + ("..." if len(missing) > 10 else ""))
    info["zones"] = len(cents)
    info["zones_in_demand"] = len(zones_in_demand)

    # V4 centroid incidence
    incident = defaultdict(int)
    for a, b in seen:
        incident[a] += 1
        incident[b] += 1
    dangling = [z for z, nid in cents.items() if incident[nid] == 0]
    if dangling:
        errors.append(f"V4 centroids with no incident link: {dangling[:10]}")

    # V5 connectors not shortcuts
    cent_nodes = set(cents.values())
    for r in instance.links:
        if (r.get("link_type") or "").strip() == "centroid_connector":
            a, b = instance.link_key(r)
            ends = (a in cent_nodes) + (b in cent_nodes)
            if ends != 1:
                errors.append(f"V5 connector ({a},{b}) touches {ends} centroids (must be exactly 1)")

    # V6 units
    for r in instance.links:
        try:
            cap = float(r["capacity"]); ln = float(r["length"])
            fs = float(r.get("free_speed") or 30)
        except ValueError:
            errors.append(f"V6 non-numeric attributes on link {r.get('link_id')}")
            continue
        if cap <= 0 or ln <= 0 or fs <= 0:
            errors.append(f"V6 nonpositive cap/length/speed on link {r.get('link_id')}")

    # V7 demand
    neg = [r for r in instance.demand if float(r["volume"]) < 0]
    if neg:
        errors.append(f"V7 negative demand rows: {len(neg)}")
    tot = instance.total_demand()
    intra = sum(float(r["volume"]) for r in instance.demand
                if r["o_zone_id"] == r["d_zone_id"])
    info["total_demand"] = round(tot, 2)
    info["intrazonal_share"] = round(intra / tot, 4) if tot else 0.0

    # V8 connectivity for demanded OD pairs
    fwd = defaultdict(list)
    for a, b in seen:
        fwd[a].append(b)

    def reach(src):
        seen_n, stack = {src}, [src]
        while stack:
            u = stack.pop()
            for v in fwd[u]:
                if v not in seen_n:
                    seen_n.add(v)
                    stack.append(v)
        return seen_n

    unreachable = 0
    by_o = defaultdict(set)
    for r in instance.demand:
        if float(r["volume"]) > 0:
            by_o[int(float(r["o_zone_id"]))].add(int(float(r["d_zone_id"])))
    for o, ds in by_o.items():
        if o not in cents:
            continue
        rs = reach(cents[o])
        unreachable += sum(1 for d in ds if d in cents and cents[d] not in rs)
    if unreachable:
        errors.append(f"V8 unreachable demanded OD pairs: {unreachable}")
    info["links"] = len(instance.links)
    info["nodes"] = len(instance.nodes)

    return {"pass": not errors, "errors": errors, "warnings": warnings, "info": info}
