"""TAPLab instance model: compact GMNS-compatible tables.

An instance folder holds node.csv / link.csv / demand.csv plus
manifest.yml and settings.yml (simple key: value text; no YAML
dependency required for the core).
"""
from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass, field
from pathlib import Path


def open_table(folder: Path, name: str):
    """Open <name>.csv, or transparently <name>.csv.gz when only the
    compressed form is bundled (large instances)."""
    plain = folder / f"{name}.csv"
    if plain.exists():
        return open(plain, encoding="utf-8-sig")
    gz = folder / f"{name}.csv.gz"
    if gz.exists():
        return gzip.open(gz, "rt", encoding="utf-8-sig")
    raise FileNotFoundError(plain)


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


def _canonical_arcs(rows):
    """Canonicalize GMNS directionality: every solver must receive the same
    directed graph. A row with directed=0 (bidirectional) expands into two
    directed arcs; the reverse arc gets link_id suffixed with 'r'."""
    out = []
    for r in rows:
        out.append(r)
        if str(r.get("directed", "1")).strip() in ("0", "false", "False"):
            rev = dict(r)
            rev["from_node_id"], rev["to_node_id"] = r["to_node_id"], r["from_node_id"]
            rev["link_id"] = f"{r.get('link_id', '')}r"
            rev["directed"] = "1"
            r["directed"] = "1"
            out.append(rev)
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
        inst.nodes = list(csv.DictReader(open_table(p, "node")))
        inst.links = _canonical_arcs(list(csv.DictReader(open_table(p, "link"))))
        inst.demand = list(csv.DictReader(open_table(p, "demand")))
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
