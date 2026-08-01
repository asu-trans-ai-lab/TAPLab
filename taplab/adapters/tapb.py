"""TAPAdapter: tap-b (Dial's Algorithm B; Boyles/SPARTA).
Set TAPLAB_TAPB_EXE. GMNS -> TNTP conversion is built in (zones must be
centroids; nodes renumbered zones-first per TNTP convention)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path


def _to_tntp(instance, work, name):
    cents = instance.centroids()
    zone_nodes = [cents[z] for z in sorted(cents)]
    others = [int(float(n["node_id"])) for n in instance.nodes
              if int(float(n["node_id"])) not in set(zone_nodes)]
    renum = {n: i for i, n in enumerate(zone_nodes + others, start=1)}
    lines = []
    for r in instance.links:
        a, b = instance.link_key(r)
        cap = float(r["capacity"])
        # tap-b uses capacity == 99999 as its ARTIFICIAL-arc sentinel and
        # silently drops such links from the flows output; nudge past it
        if cap == 99999.0:
            cap = 99998.0
        length = float(r["length"])
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or length / fs * 60.0
        B = float(r.get("vdf_alpha") or 0.15)
        P = float(r.get("vdf_beta") or 4.0)
        # full-precision %g: fixed-decimal formats silently zero out tiny
        # authoritative values (e.g. Braess fftt = 1e-8, Winnipeg alphas)
        lines.append(f"\t{renum[a]}\t{renum[b]}\t{cap:.12g}\t{length:.12g}"
                     f"\t{fftt:.12g}\t{B:.12g}\t{P:.12g}\t{fs:.6g}\t0\t1\t;")
    netdir = work / "net"
    netdir.mkdir(exist_ok=True)
    # dedicated centroids must not carry through traffic: when the network
    # has non-centroid nodes, paths may only pass through nodes > n_zones
    # (zones are renumbered first). Coincident-centroid instances such as
    # Sioux Falls keep first-thru = 1.
    first_thru = len(zone_nodes) + 1 if others else 1
    (netdir / f"{name}_net.txt").write_text(
        f"<NUMBER OF ZONES> {len(zone_nodes)}\n"
        f"<NUMBER OF NODES> {len(renum)}\n<FIRST THRU NODE> {first_thru}\n"
        f"<NUMBER OF LINKS> {len(lines)}\n<END OF METADATA>\n\n"
        + "\n".join(lines) + "\n")
    zid_of = {z: i + 1 for i, z in enumerate(sorted(cents))}
    by_o = {}
    tot = 0.0
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o in zid_of and d in zid_of:
            by_o.setdefault(zid_of[o], {})[zid_of[d]] = v
            tot += v
    parts = [f"<NUMBER OF ZONES> {len(zone_nodes)}\n<TOTAL OD FLOW> {tot:.4f}\n<END OF METADATA>\n"]
    # every zone appears as an Origin block, even with no demand — TNTP
    # convention, and TAsK's OD-matrix indexing crashes on origin gaps
    for o in range(1, len(zone_nodes) + 1):
        parts.append(f"\nOrigin {o}")
        items = sorted(by_o.get(o, {}).items())
        for i in range(0, len(items), 5):
            parts.append("    " + "".join(f"{d} : {v:.4f}; " for d, v in items[i:i + 5]))
    (netdir / f"{name}_trips.txt").write_text("\n".join(parts) + "\n")
    inv = {v: k for k, v in renum.items()}
    return inv


def solve(instance, algorithm="B", gap=1e-6, max_time=600):
    exe = os.environ.get("TAPLAB_TAPB_EXE")
    if not exe or not Path(exe).exists():
        raise RuntimeError("set TAPLAB_TAPB_EXE to the tap-b executable")
    work = Path(tempfile.mkdtemp(prefix="taplab_tapb_"))
    name = instance.path.name
    inv = _to_tntp(instance, work, name)
    (work / "params.txt").write_text(
        f"<NETWORK FILE> {name}_net.txt\n<TRIPS FILE> {name}_trips.txt\n"
        f"<FLOWS FILE> {name}_flows.txt\n<CONVERGENCE GAP> {gap}\n"
        f"<MAX RUN TIME> {max_time}\n")
    t0 = time.time()
    r = subprocess.run([exe, "params.txt"], cwd=work, capture_output=True,
                       text=True, timeout=max_time + 120)
    # BPR parameters keyed by GMNS link, to recover travel times from flows
    bpr = {}
    for lk in instance.links:
        a, b = instance.link_key(lk)
        fs = float(lk.get("free_speed") or 30) or 30
        fftt = float(lk.get("vdf_fftt") or 0) or float(lk["length"]) / fs * 60.0
        bpr[(a, b)] = (fftt, float(lk["capacity"]),
                       float(lk.get("vdf_alpha") or 0.15),
                       float(lk.get("vdf_beta") or 4.0),
                       lk.get("link_id", ""))
    flows = []
    fp = work / f"{name}_flows.txt"
    if fp.exists():
        # one record per "(tail,head) flow" line; this build repeats the flow
        # on the following line, so only per-line matches are taken
        for line in fp.read_text().splitlines():
            m = re.match(r"\s*\((\d+),(\d+)\)\s+([\d.eE+-]+)", line)
            if not m:
                continue
            a, b = inv[int(m.group(1))], inv[int(m.group(2))]
            v = float(m.group(3))
            fftt, cap, al, be, lid = bpr.get((a, b), (0.0, 1.0, 0.15, 4.0, ""))
            tt = fftt * (1.0 + al * (v / cap) ** be) if cap > 0 else fftt
            flows.append(dict(link_id=lid, from_node_id=a, to_node_id=b,
                              volume=v, travel_time=round(tt, 6)))
    gaps = re.findall(r"Iteration\s+(\d+):\s+gap\s+([\d.eE+-]+)",
                      r.stdout or "")
    if not gaps:  # some builds print "gap X" lines without iteration numbers
        raw = re.findall(r"gap[:\s]+([\d.eE+-]+)", r.stdout or "", re.I)
        gaps = list(enumerate((g for g in raw), start=1))
    conv = [(int(i), float(g), None) for i, g in gaps]
    tstt = sum(f["volume"] * f["travel_time"] for f in flows
               if isinstance(f["travel_time"], float)) or None
    return dict(flows=flows, convergence=conv,
                summary=dict(solver="tapb", algorithm="B",
                             iterations=conv[-1][0] if conv else None,
                             relative_gap=conv[-1][1] if conv else None,
                             tstt=round(tstt, 2) if tstt else None,
                             wall_time_s=round(time.time() - t0, 2),
                             workdir=str(work)))
