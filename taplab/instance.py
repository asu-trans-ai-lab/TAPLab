"""TAPLab instance model: compact GMNS-compatible tables.

An instance folder holds node.csv / link.csv / demand.csv plus
manifest.yml and settings.yml (simple key: value text; no YAML
dependency required for the core).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


def read_kv_yaml(path: Path) -> dict:
    """Minimal flat key: value reader (sufficient for manifest/settings)."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].rstrip()
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


@dataclass
class Instance:
    path: Path
    nodes: list = field(default_factory=list)
    links: list = field(default_factory=list)
    demand: list = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path) -> "Instance":
        p = Path(path)
        inst = cls(path=p)
        inst.nodes = list(csv.DictReader(open(p / "node.csv", encoding="utf-8-sig")))
        inst.links = list(csv.DictReader(open(p / "link.csv", encoding="utf-8-sig")))
        inst.demand = list(csv.DictReader(open(p / "demand.csv", encoding="utf-8-sig")))
        inst.manifest = read_kv_yaml(p / "manifest.yml")
        inst.settings = read_kv_yaml(p / "settings.yml")
        return inst

    # ---- convenience views -------------------------------------------------
    def centroids(self) -> dict:
        """zone_id -> node_id for centroid rows (node_type=centroid, or
        legacy zone_id>0 columns)."""
        out = {}
        for n in self.nodes:
            ntype = (n.get("node_type") or "").strip().lower()
            zid = n.get("zone_id") or ""
            if ntype == "centroid":
                z = int(float(n.get("zone_id") or n["node_id"]))
                out[z] = int(float(n["node_id"]))
            elif zid and float(zid) > 0:
                out[int(float(zid))] = int(float(n["node_id"]))
        return out

    def total_demand(self) -> float:
        return sum(float(r["volume"]) for r in self.demand)

    def link_key(self, r) -> tuple:
        return (int(float(r["from_node_id"])), int(float(r["to_node_id"])))
