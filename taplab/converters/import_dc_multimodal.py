"""Build the Washington DC City multimodal TAPBench instances from the
GMNS_Plus dataset (Global Dataset Project) and the DC GTFS feeds.

Two instances:

  washington_dc_driving   the OSM-derived driving network with its 179 TAZ
                          centroids and the dataset's synthetic OD demand
                          (a standard, solvable TAP instance)

  washington_dc_transit   the GTFS-derived transit service network (WMATA,
                          DC Circulator, DC Streetcar) built by gtfs2gmns
                          following the six-link-type taxonomy (sta2sta_1r
                          physical, sta2r entrance/exit, r2r service,
                          sta2sta_2r/s2s_2a transfer walking), joined to the
                          same TAZ centroids through z2sta access links
                          (walk <= 1 mi at 2 mph with a 5-minute penalty
                          beyond 0.5 mi; drive access at 40 mph), with a
                          synthetic transit OD table derived from the
                          driving OD (fixed transit share)

Usage:
  set TAPLAB_DC_DRIVING_DIR=<...\4_WashingtonDC_City_MultiModal\4.1_WashingtonDC_Driving>
  set TAPLAB_DC_GTFS_OUT=<folder holding gtfs2gmns node.csv/link.csv output>
  python -m taplab.converters.import_dc_multimodal
"""
from __future__ import annotations

import csv
import math
import os
import sys
from pathlib import Path

WALK_MPH = 2.0
DRIVE_MPH = 40.0
WALK_MAX_MI = 1.0
WALK_PENALTY_MIN = 5.0
TRANSIT_SHARE = 0.15


def _mi(x1, y1, x2, y2):
    """Haversine distance in miles."""
    r = 3958.8
    p1, p2 = math.radians(y1), math.radians(y2)
    dp = p2 - p1
    dl = math.radians(x2 - x1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _giant_scc(node_ids, arcs):
    """Largest strongly connected component (iterative Kosaraju)."""
    from collections import defaultdict
    fwd, rev = defaultdict(list), defaultdict(list)
    for a, b in arcs:
        fwd[a].append(b)
        rev[b].append(a)
    seen, order = set(), []
    for s in node_ids:
        if s in seen:
            continue
        stack = [(s, iter(fwd[s]))]
        seen.add(s)
        while stack:
            u, it = stack[-1]
            advanced = False
            for v in it:
                if v not in seen:
                    seen.add(v)
                    stack.append((v, iter(fwd[v])))
                    advanced = True
                    break
            if not advanced:
                order.append(u)
                stack.pop()
    seen2 = set()
    best = set()
    for s in reversed(order):
        if s in seen2:
            continue
        comp = {s}
        seen2.add(s)
        stack = [s]
        while stack:
            u = stack.pop()
            for v in rev[u]:
                if v not in seen2:
                    seen2.add(v)
                    comp.add(v)
                    stack.append(v)
        if len(comp) > len(best):
            best = comp
    return best


def build_driving(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "optional").mkdir(exist_ok=True)
    (dst / "reference").mkdir(exist_ok=True)
    nodes = list(csv.DictReader(open(src / "node.csv", encoding="utf-8-sig")))

    # raw OSM extracts are not strongly connected (one-ways, dead ends);
    # solvers such as tap-b patch that with artificial arcs, which silently
    # corrupts the assignment. Restrict the physical network to its giant
    # strongly connected component instead, and report what was cut.
    zone_node = {int(float(n["node_id"])) for n in nodes
                 if (n.get("zone_id") or "").strip() not in ("", "0")}
    all_links = list(csv.DictReader(open(src / "link.csv", encoding="utf-8-sig")))
    phys_arcs = []
    for r in all_links:
        a, b = int(float(r["from_node_id"])), int(float(r["to_node_id"]))
        if a not in zone_node and b not in zone_node:
            phys_arcs.append((a, b))
    phys_nodes = {a for a, _ in phys_arcs} | {b for _, b in phys_arcs}
    scc = _giant_scc(sorted(phys_nodes), phys_arcs)
    print(f"giant SCC: {len(scc)} of {len(phys_nodes)} physical nodes")
    kept_nodes = scc | zone_node

    # connectors whose attachment node fell outside the giant SCC are
    # re-snapped to the nearest SCC node (the same proximity rule that
    # generates connectors), so no zone is silently lost
    coords = {int(float(n["node_id"])): (float(n["x_coord"]), float(n["y_coord"]))
              for n in nodes}
    scc_list = sorted(scc)
    resnap = {}

    def nearest_scc(nid):
        if nid not in resnap:
            x0, y0 = coords[nid]
            resnap[nid] = min(scc_list,
                              key=lambda s: (coords[s][0] - x0) ** 2
                              + (coords[s][1] - y0) ** 2)
        return resnap[nid]

    seen_pair = set()
    n_cut = n_snap = 0
    with open(dst / "link.csv", "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["link_id", "from_node_id", "to_node_id", "link_type",
                    "directed", "length", "lanes", "capacity", "free_speed",
                    "vdf_fftt", "vdf_alpha", "vdf_beta", "allowed_uses"])
        for r in all_links:
            a, b = int(float(r["from_node_id"])), int(float(r["to_node_id"]))
            if a in zone_node and b not in scc and b not in zone_node:
                b = nearest_scc(b)
                n_snap += 1
            elif b in zone_node and a not in scc and a not in zone_node:
                a = nearest_scc(a)
                n_snap += 1
            if a not in kept_nodes or b not in kept_nodes or (a, b) in seen_pair:
                n_cut += 1
                continue
            seen_pair.add((a, b))
            ltype = "centroid_connector" \
                if (r.get("link_type_name") or "").strip() == "connector" \
                or a in zone_node or b in zone_node \
                else ((r.get("link_type_name") or "arterial").strip() or "arterial")
            w.writerow([r["link_id"], a, b, ltype, 1,
                        r.get("vdf_length_mi") or r["length"],
                        r.get("lanes") or 1, r["capacity"],
                        r.get("vdf_free_speed_mph") or r.get("free_speed") or 30,
                        r.get("vdf_fftt") or "",
                        r.get("vdf_alpha") or 0.15,
                        r.get("vdf_beta") or 4.0, "auto"])
    print(f"cut {n_cut} links outside the SCC or duplicated")
    used = {a for a, _ in seen_pair} | {b for _, b in seen_pair}
    with open(dst / "node.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "node_type", "zone_id", "x_coord", "y_coord"])
        for n in nodes:
            nid = int(float(n["node_id"]))
            if nid not in used:
                continue
            zid = (n.get("zone_id") or "").strip()
            is_c = zid not in ("", "0") and float(zid) > 0
            w.writerow([nid, "centroid" if is_c else "intersection",
                        int(float(zid)) if is_c else "",
                        n["x_coord"], n["y_coord"]])
    # raw OSM extracts leave some zone pairs disconnected in the directed
    # graph; drop those OD pairs EXPLICITLY and report the drop — a bundled
    # instance must pass V8, and silent truncation is worse than a logged one
    from collections import defaultdict
    fwd = defaultdict(list)
    for r in csv.DictReader(open(dst / "link.csv")):
        fwd[int(float(r["from_node_id"]))].append(int(float(r["to_node_id"])))
    cent = {}
    for n in csv.DictReader(open(dst / "node.csv")):
        if n["node_type"] == "centroid":
            cent[int(float(n["zone_id"]))] = int(float(n["node_id"]))
    cent_nodes = set(cent.values())

    def reach(o):
        # centroid-blocked reachability: solvers refuse paths THROUGH
        # centroids, so connectivity must be judged under the same rule
        seen = {o}
        stack = [o]
        while stack:
            u = stack.pop()
            if u != o and u in cent_nodes:
                continue
            for v2 in fwd[u]:
                if v2 not in seen:
                    seen.add(v2)
                    stack.append(v2)
        return seen

    reach_cache = {}
    tot = dropped = drop_vol = 0.0
    n_drop = 0
    with open(src / "demand.csv", encoding="utf-8-sig") as f, \
         open(dst / "demand.csv", "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["o_zone_id", "d_zone_id", "volume", "period", "agent_type"])
        for r in csv.DictReader(f):
            v = float(r["volume"])
            if v <= 0:
                continue
            o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
            if o not in cent or d not in cent:
                n_drop += 1
                drop_vol += v
                continue
            if o not in reach_cache:
                reach_cache[o] = reach(cent[o])
            if cent[d] not in reach_cache[o]:
                n_drop += 1
                drop_vol += v
                continue
            w.writerow([o, d, r["volume"], "AM", "auto"])
            tot += v
    (dst / "settings.yml").write_text(
        "cap_per_lane: no\ndefault_gap: 1e-4\nperiod: AM\n")
    print(f"driving: {len(nodes)} nodes, demand kept {tot:,.0f}; "
          f"DROPPED {n_drop} disconnected OD pairs ({drop_vol:,.0f} trips)")


def build_transit(gtfs_out: Path, driving_src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "optional").mkdir(exist_ok=True)
    (dst / "reference").mkdir(exist_ok=True)

    tnodes = list(csv.DictReader(open(gtfs_out / "source_node.csv",
                                      encoding="utf-8-sig")))
    tlinks = list(csv.DictReader(open(gtfs_out / "link.csv",
                                      encoding="utf-8-sig")))
    zones = [n for n in csv.DictReader(open(driving_src / "node.csv",
                                            encoding="utf-8-sig"))
             if (n.get("zone_id") or "").strip() not in ("", "0")]

    with open(dst / "node.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "node_type", "zone_id", "x_coord", "y_coord"])
        for z in zones:
            w.writerow([10000 + int(float(z["zone_id"])), "centroid",
                        int(float(z["zone_id"])), z["x_coord"], z["y_coord"]])
        for n in tnodes:
            w.writerow([int(float(n["node_id"])),
                        (n.get("node_type") or "stop") or "stop", "",
                        n["x_coord"], n["y_coord"]])

    # physical stops (not route-level service nodes) take access links
    phys = [n for n in tnodes
            if not (n.get("directed_route_id") or "").strip()]

    n_access = 0
    with open(dst / "link.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["link_id", "from_node_id", "to_node_id", "link_type",
                    "directed", "length", "lanes", "capacity", "free_speed",
                    "vdf_fftt", "vdf_alpha", "vdf_beta", "allowed_uses"])
        lid = 0
        for r in tlinks:
            lid += 1
            fftt = r.get("VDF_fftt1") or 0
            w.writerow([lid, int(float(r["from_node_id"])),
                        int(float(r["to_node_id"])),
                        (r.get("link_type_name") or "transit").strip(), 1,
                        r.get("length") or 0, 1,
                        r.get("VDF_cap1") or r.get("capacity") or 9999,
                        r.get("free_speed") or 20, fftt,
                        r.get("VDF_alpha1") or 0.15,
                        r.get("VDF_beta1") or 4.0, "transit"])
        for z in zones:
            zx, zy = float(z["x_coord"]), float(z["y_coord"])
            znid = 10000 + int(float(z["zone_id"]))
            near = sorted(
                ((_mi(zx, zy, float(n["x_coord"]), float(n["y_coord"])), n)
                 for n in phys), key=lambda p: p[0])[:8]
            for dist, n in near:
                if dist > WALK_MAX_MI:
                    continue
                fftt = dist / WALK_MPH * 60.0 \
                    + (WALK_PENALTY_MIN if dist > 0.5 else 0.0)
                for a, b in ((znid, int(float(n["node_id"]))),
                             (int(float(n["node_id"])), znid)):
                    lid += 1
                    n_access += 1
                    w.writerow([lid, a, b, "centroid_connector", 1,
                                round(dist, 4), 1, 99999, WALK_MPH,
                                round(fftt, 4), 0.15, 4.0, "transit"])

    tot = 0.0
    zone_ids = {int(float(z["zone_id"])) for z in zones}
    with open(driving_src / "demand.csv", encoding="utf-8-sig") as f, \
         open(dst / "demand.csv", "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["o_zone_id", "d_zone_id", "volume", "period", "agent_type"])
        for r in csv.DictReader(f):
            v = float(r["volume"]) * TRANSIT_SHARE
            o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
            if v > 0 and o in zone_ids and d in zone_ids:
                w.writerow([o, d, round(v, 3), "AM", "w_bus_metro"])
                tot += v
    (dst / "settings.yml").write_text(
        "cap_per_lane: no\ndefault_gap: 1e-4\nperiod: AM\n")
    print(f"transit: {len(tnodes)} service nodes, {len(tlinks)} service links,"
          f" {n_access} access links, synthetic demand {tot:,.0f}"
          f" ({int(TRANSIT_SHARE*100)}% share)")


if __name__ == "__main__":
    drv = os.environ.get("TAPLAB_DC_DRIVING_DIR")
    if not drv or not Path(drv).exists():
        sys.exit("set TAPLAB_DC_DRIVING_DIR to the 4.1_WashingtonDC_Driving folder")
    build_driving(Path(drv), Path("tapbench/washington_dc_driving"))
    gt = os.environ.get("TAPLAB_DC_GTFS_OUT")
    if gt and Path(gt).exists():
        build_transit(Path(gt), Path(drv),
                      Path("tapbench/washington_dc_transit"))
    else:
        print("TAPLAB_DC_GTFS_OUT not set; skipped the transit instance")
