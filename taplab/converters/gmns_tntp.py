"""GMNS <-> TNTP converters for the GMNSforTAP_algorithms package.

GMNS side: node.csv (node_id, zone_id, x_coord, y_coord),
           link.csv (link_id, from_node_id, to_node_id, length, lanes,
                     capacity, free_speed, vdf_alpha, vdf_beta, ...),
           demand.csv (o_zone_id, d_zone_id, volume).
TNTP side: <name>_net.txt / <name>_trips.txt in Hillel Bar-Gera's
           TransportationNetworks format (consumed by tap-b, TAsK, TAPAS).

Conventions
- GMNS capacity is treated as TOTAL link capacity (veh/h). If your GMNS
  stores per-lane capacity, pass --cap-per-lane to multiply by lanes.
- fftt(min) = length / free_speed * 60; length unit passes through.
- TNTP node numbering must be 1..N with zones first; the converter
  renumbers and writes the mapping to <name>_node_map.csv.

Usage
  python gmns_tntp.py gmns2tntp <gmns_dir> <out_dir> <name> [--cap-per-lane]
  python gmns_tntp.py tntp2gmns <net.txt> <trips.txt> <out_gmns_dir>
  python gmns_tntp.py flows2gmns <flows_file> <node_map.csv> <out_csv>
      flows_file: tap-b/TAsK link-flow output (tail head flow cost)
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------- gmns2tntp
def gmns2tntp(gmns_dir, out_dir, name, cap_per_lane=False):
    gmns_dir, out_dir = Path(gmns_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes = list(csv.DictReader(open(gmns_dir / "node.csv", encoding="utf-8-sig")))
    links = list(csv.DictReader(open(gmns_dir / "link.csv", encoding="utf-8-sig")))
    dem_path = next((p for p in [gmns_dir / "demand.csv"] if p.exists()), None)
    demands = list(csv.DictReader(open(dem_path, encoding="utf-8-sig"))) if dem_path else []

    def zid(n):
        z = (n.get("zone_id") or "").strip()
        return int(float(z)) if z and float(z) > 0 else 0

    zones = [n for n in nodes if zid(n)]
    others = [n for n in nodes if not zid(n)]
    zones.sort(key=zid)
    renum, zone_of = {}, {}
    for i, n in enumerate(zones + others, start=1):
        renum[str(int(float(n["node_id"])))] = i
        if zid(n):
            zone_of[zid(n)] = i
    n_zones = len(zones)

    with open(out_dir / f"{name}_net.txt", "w", newline="") as f:
        f.write(f"<NUMBER OF ZONES> {n_zones}\n<NUMBER OF NODES> {len(nodes)}\n")
        f.write(f"<FIRST THRU NODE> {1}\n<NUMBER OF LINKS> {len(links)}\n")
        f.write("<END OF METADATA>\n\n~\ttail\thead\tcapacity\tlength\tfftt\tB\tPower\tspeed\ttoll\ttype\t\n")
        for r in links:
            a = renum[str(int(float(r["from_node_id"])))]
            b = renum[str(int(float(r["to_node_id"])))]
            lanes = float(r.get("lanes") or 1) or 1
            cap = float(r["capacity"]) * (lanes if cap_per_lane else 1.0)
            length = float(r["length"])
            fs = float(r.get("free_speed") or 30) or 30
            fftt = length / fs * 60.0
            B = float(r.get("vdf_alpha") or 0.15)
            P = float(r.get("vdf_beta") or 4.0)
            f.write(f"\t{a}\t{b}\t{cap:.4f}\t{length:.6f}\t{fftt:.6f}"
                    f"\t{B:.4f}\t{P:.2f}\t{fs:.2f}\t0\t1\t;\n")

    tot = 0.0
    by_o = {}
    for r in demands:
        o = zone_of.get(int(float(r["o_zone_id"])))
        d = zone_of.get(int(float(r["d_zone_id"])))
        v = float(r["volume"])
        if o and d and v > 0:
            by_o.setdefault(o, {})[d] = by_o.setdefault(o, {}).get(d, 0.0) + v
            tot += v
    with open(out_dir / f"{name}_trips.txt", "w", newline="") as f:
        f.write(f"<NUMBER OF ZONES> {n_zones}\n<TOTAL OD FLOW> {tot:.4f}\n<END OF METADATA>\n\n")
        for o in sorted(by_o):
            f.write(f"Origin {o}\n")
            items = sorted(by_o[o].items())
            for i in range(0, len(items), 5):
                f.write("    " + "".join(f"{d} : {v:.4f}; "
                                         for d, v in items[i:i + 5]) + "\n")
            f.write("\n")

    with open(out_dir / f"{name}_node_map.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gmns_node_id", "tntp_node_id", "zone_id"])
        for n in zones + others:
            g = str(int(float(n["node_id"])))
            w.writerow([g, renum[g], zid(n) or ""])
    print(f"gmns2tntp: {n_zones} zones, {len(nodes)} nodes, "
          f"{len(links)} links, OD total {tot:,.0f} -> {out_dir}/{name}_*")


# ---------------------------------------------------------------- tntp2gmns
def tntp2gmns(net_txt, trips_txt, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt = Path(net_txt).read_text()
    n_zones = int(re.search(r"<NUMBER OF ZONES>\s*(\d+)", txt).group(1))
    body = txt.split("<END OF METADATA>")[1]
    links = []
    for line in body.splitlines():
        parts = line.replace(";", " ").split()
        if len(parts) >= 8 and parts[0].lstrip("-").isdigit():
            a, b = int(parts[0]), int(parts[1])
            cap, length, fftt, B, P = map(float, parts[2:7])
            speed = float(parts[7]) if len(parts) > 7 else 0
            if fftt > 0 and length > 0:
                fs = length / (fftt / 60.0)
            else:
                fs = speed or 30.0
            links.append((a, b, cap, length, fs, B, P))
    node_ids = sorted({a for a, *_ in links} | {l[1] for l in links})
    with open(out_dir / "node.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "zone_id", "x_coord", "y_coord"])
        for n in node_ids:
            w.writerow([n, n if n <= n_zones else "", 0, 0])
    with open(out_dir / "link.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["link_id", "from_node_id", "to_node_id", "length",
                    "lanes", "capacity", "free_speed", "vdf_alpha", "vdf_beta"])
        for i, (a, b, cap, length, fs, B, P) in enumerate(links, 1):
            w.writerow([i, a, b, f"{length:.6f}", 1, f"{cap:.4f}",
                        f"{fs:.4f}", B, P])
    dem = []
    if trips_txt and Path(trips_txt).exists():
        cur_o = None
        for line in Path(trips_txt).read_text().splitlines():
            m = re.match(r"\s*Origin\s+(\d+)", line)
            if m:
                cur_o = int(m.group(1))
                continue
            if cur_o:
                for d, v in re.findall(r"(\d+)\s*:\s*([\d.eE+-]+)\s*;", line):
                    dem.append((cur_o, int(d), float(v)))
    with open(out_dir / "demand.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["o_zone_id", "d_zone_id", "volume"])
        for o, d, v in dem:
            w.writerow([o, d, f"{v:.4f}"])
    print(f"tntp2gmns: {len(node_ids)} nodes ({n_zones} zones), "
          f"{len(links)} links, {len(dem)} OD pairs -> {out_dir}")


# --------------------------------------------------------------- flows2gmns
def flows2gmns(flows_file, node_map_csv, out_csv):
    inv = {}
    for r in csv.DictReader(open(node_map_csv)):
        inv[int(r["tntp_node_id"])] = r["gmns_node_id"]
    rows = []
    for line in Path(flows_file).read_text().splitlines():
        # tap-b: "(tail,head) flow"; TAsK: "tail head flow cost"
        m = re.match(r"\s*\((\d+),(\d+)\)\s+([\d.eE+-]+)(?:\s+([\d.eE+-]+))?",
                     line) or \
            re.match(r"\s*(\d+)\s+(\d+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)", line)
        if m:
            a, b, flow = int(m.group(1)), int(m.group(2)), float(m.group(3))
            cost = m.group(4)
            rows.append([inv.get(a, a), inv.get(b, b), f"{flow:.4f}",
                         f"{float(cost):.6f}" if cost else ""])
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["from_node_id", "to_node_id", "volume", "travel_time"])
        w.writerows(rows)
    print(f"flows2gmns: {len(rows)} links -> {out_csv}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "gmns2tntp":
        gmns2tntp(sys.argv[2], sys.argv[3], sys.argv[4],
                  cap_per_lane="--cap-per-lane" in sys.argv)
    elif cmd == "tntp2gmns":
        tntp2gmns(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "flows2gmns":
        flows2gmns(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
