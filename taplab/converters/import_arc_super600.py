"""Import the ARC Atlanta super-600 model (600 aggregated zones over the
full regional network) into a TAPLab instance.

The ARC model data is licensed and is NOT bundled in this repository. Set
TAPLAB_ARC_SUPER600_DIR to a local copy of the arc_super_600 folder (node.csv,
link.csv, demand_sov/hov2/hov3.csv) and run:

    python -m taplab.converters.import_arc_super600 tapbench/arc_atlanta_super600

The generated CSVs are gitignored; only this importer and the instance
README/manifest are version-controlled.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path


def import_arc(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "optional").mkdir(exist_ok=True)
    (dst / "reference").mkdir(exist_ok=True)

    with open(src / "node.csv", encoding="utf-8-sig") as f, \
         open(dst / "node.csv", "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["node_id", "node_type", "zone_id", "x_coord", "y_coord"])
        for r in csv.DictReader(f):
            zid = r.get("zone_id") or ""
            is_c = zid and float(zid) > 0
            w.writerow([int(float(r["node_id"])),
                        "centroid" if is_c else "intersection",
                        int(float(zid)) if is_c else "",
                        r["x_coord"], r["y_coord"]])

    n_ref = 0
    with open(src / "link.csv", encoding="utf-8-sig") as f, \
         open(dst / "link.csv", "w", newline="") as g, \
         open(dst / "reference" / "link_performance.csv", "w", newline="") as h:
        w = csv.writer(g)
        w.writerow(["link_id", "from_node_id", "to_node_id", "link_type",
                    "directed", "length", "lanes", "capacity", "free_speed",
                    "vdf_fftt", "vdf_alpha", "vdf_beta", "allowed_uses"])
        wr = csv.writer(h)
        wr.writerow(["from_node_id", "to_node_id", "volume", "travel_time"])
        for r in csv.DictReader(f):
            a, b = int(float(r["from_node_id"])), int(float(r["to_node_id"]))
            ltype = "centroid_connector" if r.get("link_type") == "9" \
                else (r.get("factype") or "arterial")
            w.writerow([r["link_id"], a, b, ltype, 1,
                        r.get("vdf_length_mi") or r["length"],
                        r.get("lanes") or 1, r["capacity"],
                        r.get("vdf_free_speed_mph") or r["free_speed"],
                        r.get("vdf_fftt") or "",
                        r.get("vdf_alpha") or 0.15,
                        r.get("vdf_beta") or 4.0, "auto"])
            rv = r.get("ref_volume")
            if rv not in (None, "", "0", "0.0"):
                wr.writerow([a, b, rv, ""])
                n_ref += 1

    tot = 0.0
    with open(dst / "demand.csv", "w", newline="") as g:
        w = csv.writer(g)
        w.writerow(["o_zone_id", "d_zone_id", "volume", "period", "agent_type"])
        for cls in ("sov", "hov2", "hov3"):
            p = src / f"demand_{cls}.csv"
            if not p.exists():
                continue
            for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                v = float(r["volume"])
                if v > 0:
                    w.writerow([r["o_zone_id"], r["d_zone_id"],
                                r["volume"], "AM", cls])
                    tot += v

    (dst / "settings.yml").write_text(
        "cap_per_lane: no\ndefault_gap: 1e-4\nperiod: AM\n")
    (dst / "manifest.yml").write_text(
        "name: arc_atlanta_super600\n"
        "title: ARC Atlanta super-600 (600 aggregated zones, full regional network)\n"
        "source: ARC activity-based model AM assignment, aggregated to 600 super-zones (licensed; import locally)\n"
        "centroid_convention: node_type=centroid; connectors from ARC link_type 9\n"
        "reference: reference/link_performance.csv = ARC AM reference volumes where available\n"
        "license: ARC model data is licensed and must not be redistributed\n")
    print(f"imported: demand total {tot:,.0f}; reference links {n_ref:,}")


if __name__ == "__main__":
    src = os.environ.get("TAPLAB_ARC_SUPER600_DIR")
    if not src or not Path(src).exists():
        sys.exit("set TAPLAB_ARC_SUPER600_DIR to the arc_super_600 folder")
    dst = Path(sys.argv[1] if len(sys.argv) > 1 else "tapbench/arc_atlanta_super600")
    import_arc(Path(src), dst)
