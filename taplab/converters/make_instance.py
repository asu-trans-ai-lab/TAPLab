"""Build a compact TAPLab instance from a legacy GMNS folder (node.csv with
zone_id column; link.csv with capacity / free_speed / vdf_* fields), such as
the output of gmns_tntp.tntp2gmns.

    python -m taplab.converters.make_instance <src_gmns_dir> <dst_instance_dir>
        [--name NAME] [--gzip-demand] [--ref-from-tntp FLOW_FILE]
        [--ref-from-column]

--gzip-demand    write demand.csv.gz (large instances; the loader reads both)
--ref-from-tntp  build reference/link_performance.csv from a TNTP flow file
                 ("From To Volume Cost" table, e.g. *_flow.tntp best-known)
--ref-from-column  take reference volumes from a ref_volume column in link.csv
"""
from __future__ import annotations

import argparse
import csv
import gzip
from pathlib import Path


def build(src: Path, dst: Path, name=None, gzip_demand=False,
          ref_from_tntp=None, ref_from_column=False):
    name = name or dst.name
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "optional").mkdir(exist_ok=True)
    (dst / "reference").mkdir(exist_ok=True)

    nodes = list(csv.DictReader(open(src / "node.csv", encoding="utf-8-sig")))
    cent = set()
    with open(dst / "node.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "node_type", "zone_id", "x_coord", "y_coord"])
        for n in nodes:
            zid = n.get("zone_id") or ""
            is_c = zid not in ("", "0", "0.0") and float(zid) > 0
            nid = int(float(n["node_id"]))
            if is_c:
                cent.add(nid)
            w.writerow([nid, "centroid" if is_c else "intersection",
                        int(float(zid)) if is_c else "",
                        n.get("x_coord", 0), n.get("y_coord", 0)])

    def g(r, *keys, default=""):
        for k in keys:
            if r.get(k) not in (None, ""):
                return r[k]
        return default

    n_ref = 0
    refw = None
    if ref_from_column:
        reff = open(dst / "reference" / "link_performance.csv", "w", newline="")
        refw = csv.writer(reff)
        refw.writerow(["from_node_id", "to_node_id", "volume", "travel_time"])
    with open(src / "link.csv", encoding="utf-8-sig") as f, \
         open(dst / "link.csv", "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["link_id", "from_node_id", "to_node_id", "link_type",
                    "directed", "length", "lanes", "capacity", "free_speed",
                    "vdf_fftt", "vdf_alpha", "vdf_beta", "allowed_uses"])
        for r in csv.DictReader(f):
            a, b = int(float(r["from_node_id"])), int(float(r["to_node_id"]))
            ltype = "centroid_connector" if (a in cent) != (b in cent) \
                else "arterial"
            fs = float(g(r, "vdf_free_speed_mph", "free_speed", default=30) or 30)
            length = float(g(r, "vdf_length_mi", "length", default=0) or 0)
            fftt = float(g(r, "VDF_fftt", "vdf_fftt", default=0) or 0) \
                or (length / fs * 60.0 if fs > 0 else 0)
            w.writerow([r.get("link_id", ""), a, b, ltype, 1,
                        length, g(r, "lanes", default=1),
                        g(r, "capacity"), fs, f"{fftt:.12g}",
                        g(r, "VDF_alpha", "vdf_alpha", default=0.15),
                        g(r, "VDF_beta", "vdf_beta", default=4.0), "auto"])
            if refw is not None:
                rv = g(r, "ref_volume")
                if rv not in ("", None):
                    refw.writerow([a, b, rv, g(r, "ref_cost")])
                    n_ref += 1

    if ref_from_tntp:
        with open(ref_from_tntp) as f, \
             open(dst / "reference" / "link_performance.csv", "w",
                  newline="") as out:
            w = csv.writer(out)
            w.writerow(["from_node_id", "to_node_id", "volume", "travel_time"])
            next(f)
            for line in f:
                p = line.split()
                if len(p) >= 3 and p[0].isdigit():
                    w.writerow([int(p[0]), int(p[1]), p[2],
                                p[3] if len(p) > 3 else ""])
                    n_ref += 1

    opener = (lambda q: gzip.open(q, "wt", newline="")) if gzip_demand \
        else (lambda q: open(q, "w", newline=""))
    dname = "demand.csv.gz" if gzip_demand else "demand.csv"
    tot = 0.0
    with open(src / "demand.csv", encoding="utf-8-sig") as f, \
         opener(dst / dname) as out:
        w = csv.writer(out)
        w.writerow(["o_zone_id", "d_zone_id", "volume", "period", "agent_type"])
        for r in csv.DictReader(f):
            v = float(r["volume"])
            if v > 0:
                w.writerow([int(float(r["o_zone_id"])),
                            int(float(r["d_zone_id"])), r["volume"],
                            "AM", "auto"])
                tot += v

    if not (dst / "settings.yml").exists():
        (dst / "settings.yml").write_text(
            "cap_per_lane: no\ndefault_gap: 1e-4\nperiod: AM\n")
    print(f"{name}: nodes {len(nodes)}, zones {len(cent)}, "
          f"demand {tot:,.1f}, reference links {n_ref:,}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--name")
    ap.add_argument("--gzip-demand", action="store_true")
    ap.add_argument("--ref-from-tntp")
    ap.add_argument("--ref-from-column", action="store_true")
    a = ap.parse_args()
    build(Path(a.src), Path(a.dst), a.name, a.gzip_demand,
          a.ref_from_tntp, a.ref_from_column)
