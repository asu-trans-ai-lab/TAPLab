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
        length = float(r["length"])
        fs = float(r.get("free_speed") or 30) or 30
        fftt = float(r.get("vdf_fftt") or 0) or length / fs * 60.0
        B = float(r.get("vdf_alpha") or 0.15)
        P = float(r.get("vdf_beta") or 4.0)
        lines.append(f"\t{renum[a]}\t{renum[b]}\t{cap:.4f}\t{length:.6f}"
                     f"\t{fftt:.6f}\t{B:.4f}\t{P:.2f}\t{fs:.2f}\t0\t1\t;")
    netdir = work / "net"
    netdir.mkdir(exist_ok=True)
    (netdir / f"{name}_net.txt").write_text(
        f"<NUMBER OF ZONES> {len(zone_nodes)}\n"
        f"<NUMBER OF NODES> {len(renum)}\n<FIRST THRU NODE> 1\n"
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
    for o in sorted(by_o):
        parts.append(f"\nOrigin {o}")
        items = sorted(by_o[o].items())
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
    flows = []
    fp = work / f"{name}_flows.txt"
    if fp.exists():
        for line in fp.read_text().splitlines():
            m = re.match(r"\s*\((\d+),(\d+)\)\s+([\d.eE+-]+)", line)
            if m:
                flows.append(dict(from_node_id=inv[int(m.group(1))],
                                  to_node_id=inv[int(m.group(2))],
                                  volume=float(m.group(3)), travel_time=""))
    gaps = re.findall(r"Iteration\s+(\d+):\s+gap\s+([\d.eE+-]+)", r.stdout)
    return dict(flows=flows,
                convergence=[(int(i), float(g), None) for i, g in gaps],
                summary=dict(solver="tapb", algorithm="B",
                             wall_time_s=round(time.time() - t0, 2),
                             workdir=str(work)))
