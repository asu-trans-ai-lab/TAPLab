"""TAPForge: parametric instance generator — the controlled laboratory side
of TAPLab. Every generated instance records its full parameter set and seed
in manifest.yml, so any instance is reproducible from its manifest alone.

  taplab forge diamond --out tapbench/forge/diamond
  taplab forge braess  --demand 4000 --with-diagonal
  taplab forge grid --n 10 --pattern corner --barrier --braess-diagonal \
      --corridors 2 --perturb 0.01 --origins 4 --dests-per-origin 4 --seed 1

Grid options (track A2/A3):
  --pattern corner|uniform|radial   demand structure
  --origins / --dests-per-origin    the |O| x |D_o| factorial (0 = all)
  --corridors K                     every ceil(n/K)-th row gets 3x capacity
  --barrier                         cut the middle column except one gap
  --braess-diagonal                 add a fast diagonal across the center
  --perturb EPS                     seeded multiplicative fftt noise
  --congestion low|medium|high      demand scaled to ~0.3/0.7/1.1 mean v/c
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path


def _write(dst: Path, nodes, links, demand, manifest: dict):
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "optional").mkdir(exist_ok=True)
    (dst / "reference").mkdir(exist_ok=True)
    with open(dst / "node.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node_id", "node_type", "zone_id", "x_coord", "y_coord"])
        w.writerows(nodes)
    with open(dst / "link.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["link_id", "from_node_id", "to_node_id", "link_type",
                    "directed", "length", "lanes", "capacity", "free_speed",
                    "vdf_fftt", "vdf_alpha", "vdf_beta", "allowed_uses"])
        w.writerows(links)
    with open(dst / "demand.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["o_zone_id", "d_zone_id", "volume", "period", "agent_type"])
        w.writerows(demand)
    (dst / "settings.yml").write_text(
        "cap_per_lane: no\ndefault_gap: 1e-6\nperiod: AM\n")
    lines = [f"name: {dst.name}", "generator: TAPForge"]
    lines += [f"{k}: {v}" for k, v in manifest.items()]
    (dst / "manifest.yml").write_text("\n".join(lines) + "\n")
    total = sum(float(r[2]) for r in demand)
    print(f"forged {dst.name}: {len(nodes)} nodes, {len(links)} links, "
          f"{len(demand)} OD rows, demand {total:,.0f} -> {dst}")


def forge_diamond(out: Path, demand=3000.0):
    """A0 diamond: one OD, two two-link routes with asymmetric fftt but
    symmetric capacity — equilibrium equalizes route costs, not flows."""
    nodes = [(1, "centroid", 1, 0, 0), (2, "intersection", "", 1, 1),
             (3, "intersection", "", 1, -1), (4, "centroid", 4, 2, 0)]
    links = [(1, 1, 2, "centroid_connector", 1, 1, 1, 2000, 30, 5, 0.15, 4, "auto"),
             (2, 1, 3, "centroid_connector", 1, 1, 1, 2000, 30, 8, 0.15, 4, "auto"),
             (3, 2, 4, "arterial", 1, 1, 1, 2000, 30, 8, 0.15, 4, "auto"),
             (4, 3, 4, "arterial", 1, 1, 1, 2000, 30, 5, 0.15, 4, "auto")]
    dem = [(1, 4, demand, "AM", "auto")]
    _write(out, nodes, links, dem, dict(track="A0", type="diamond",
                                        demand=demand))


def forge_braess(out: Path, demand=4000.0, with_diagonal=True):
    """A0 Braess: with the diagonal, equilibrium routes everyone through it
    and everyone is worse off. Links use alpha=1, beta=1 (affine BPR) so the
    classic construction carries over: t_OA = t_BD = 1+x/100 (steep),
    t_AD = t_OB = 45 flat, diagonal t_AB ~ 0."""
    nodes = [(1, "centroid", 1, 0, 0), (2, "intersection", "", 1, 1),
             (3, "intersection", "", 1, -1), (4, "centroid", 4, 2, 0)]
    # steep links: t = 1 + 0.01x  (fftt=1, alpha=40, cap=4000, beta=1)
    # flat links:  t = 45         (alpha=0)
    # at demand 4000: no diagonal -> 66 min per route; with diagonal ->
    # everyone through it at 82.25 min. Worse for all, yet the equilibrium.
    links = [(1, 1, 2, "centroid_connector", 1, 1, 1, 4000, 30, 1, 40.0, 1, "auto"),
             (2, 1, 3, "centroid_connector", 1, 1, 1, 10000, 30, 45, 0.0, 1, "auto"),
             (3, 2, 4, "arterial", 1, 1, 1, 10000, 30, 45, 0.0, 1, "auto"),
             (4, 3, 4, "arterial", 1, 1, 1, 4000, 30, 1, 40.0, 1, "auto")]
    if with_diagonal:
        links.append((5, 2, 3, "arterial", 1, 0.1, 1, 10000, 30, 0.25, 0.0, 1, "auto"))
    dem = [(1, 4, demand, "AM", "auto")]
    _write(out, nodes, links, dem, dict(track="A0", type="braess",
                                        demand=demand,
                                        with_diagonal=with_diagonal))


def forge_grid(out: Path, n=10, pattern="corner", origins=0,
               dests_per_origin=0, corridors=0, barrier=False,
               braess_diagonal=False, perturb=0.0, congestion="medium",
               seed=1):
    """A2/A3 Manhattan grid: n x n intersections, bidirectional streets as
    two directed arcs, zone centroids on the boundary. A compact physical
    network with a combinatorially large path space."""
    rng = random.Random(seed)
    nid = lambda i, j: i * n + j + 1
    nodes = []
    boundary = []
    for i in range(n):
        for j in range(n):
            on_b = i in (0, n - 1) or j in (0, n - 1)
            nodes.append([nid(i, j), "intersection", "", j, -i])
            if on_b:
                boundary.append((i, j))
    # centroids: one per boundary intersection, offset outward
    zid = 0
    zone_of = {}
    cent_rows = []
    for (i, j) in boundary:
        zid += 1
        zone_of[(i, j)] = zid
        cent_rows.append([10000 + zid, "centroid", zid,
                          j + (0.4 if j == n - 1 else -0.4 if j == 0 else 0),
                          -i + (0.4 if i == 0 else -0.4 if i == n - 1 else 0)])
    nodes = cent_rows + nodes

    links = []
    lid = 0

    def add(a, b, ltype, cap, fftt, alpha=0.15, beta=4.0, length=1.0):
        nonlocal lid
        lid += 1
        links.append([lid, a, b, ltype, 1, length, 1, cap, 30,
                      round(fftt, 6), alpha, beta, "auto"])

    base_cap, base_fftt = 1000.0, 2.0
    wide = set()
    if corridors > 0:
        step = max(2, n // (corridors + 1))
        wide = {r for r in range(step, n, step)}
    gap_row = n // 2
    mid_col = n // 2
    for i in range(n):
        for j in range(n):
            cap_h = base_cap * (3.0 if i in wide else 1.0)
            f = base_fftt * (1 + perturb * (rng.random() - 0.5) * 2) \
                if perturb else base_fftt
            if j + 1 < n:
                if not (barrier and j + 1 == mid_col and i != gap_row):
                    add(nid(i, j), nid(i, j + 1), "arterial", cap_h, f)
                if not (barrier and j + 1 == mid_col and i != gap_row):
                    add(nid(i, j + 1), nid(i, j), "arterial", cap_h, f)
            if i + 1 < n:
                f2 = base_fftt * (1 + perturb * (rng.random() - 0.5) * 2) \
                    if perturb else base_fftt
                add(nid(i, j), nid(i + 1, j), "arterial", base_cap, f2)
                add(nid(i + 1, j), nid(i, j), "arterial", base_cap, f2)
    if braess_diagonal:
        c = n // 2
        add(nid(c - 1, c - 1), nid(c, c), "arterial", 3 * base_cap,
            0.5 * base_fftt, length=1.4)
    for (i, j), z in zone_of.items():
        add(10000 + z, nid(i, j), "centroid_connector", 1e5, 0.5)
        add(nid(i, j), 10000 + z, "centroid_connector", 1e5, 0.5)

    # demand: pattern x congestion x O/D factorial
    zones = sorted(zone_of.values())
    corner = [zone_of[(0, 0)], zone_of[(n - 1, n - 1)],
              zone_of[(0, n - 1)], zone_of[(n - 1, 0)]]
    olist = zones if origins in (0, None) else \
        rng.sample(zones, min(origins, len(zones)))
    scale = dict(low=0.3, medium=0.7, high=1.1)[congestion]
    per_target = scale * base_cap * n / max(len(olist), 1)
    dem = []
    if pattern == "corner":
        dem = [(corner[0], corner[1], round(scale * base_cap * 2, 1),
                "AM", "auto")]
    else:
        for o in olist:
            if pattern == "radial":
                dl = [zone_of[min(zone_of, key=lambda ij:
                      abs(ij[0] - n // 2) + abs(ij[1] - n // 2))]]
            else:  # uniform
                cand = [z for z in zones if z != o]
                dl = cand if dests_per_origin in (0, None) else \
                    rng.sample(cand, min(dests_per_origin, len(cand)))
            for d in dl:
                if d != o:
                    dem.append((o, d, round(per_target / max(len(dl), 1), 2),
                                "AM", "auto"))
    _write(out, nodes, links, dem, dict(
        track="A2/A3", type="grid", n=n, pattern=pattern, origins=origins,
        dests_per_origin=dests_per_origin, corridors=corridors,
        barrier=barrier, braess_diagonal=braess_diagonal, perturb=perturb,
        congestion=congestion, seed=seed))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="taplab forge")
    ap.add_argument("kind", choices=["diamond", "braess", "grid"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--demand", type=float, default=4000.0)
    ap.add_argument("--with-diagonal", action="store_true", default=True)
    ap.add_argument("--no-diagonal", dest="with_diagonal", action="store_false")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--pattern", default="corner",
                    choices=["corner", "uniform", "radial"])
    ap.add_argument("--origins", type=int, default=0)
    ap.add_argument("--dests-per-origin", type=int, default=0)
    ap.add_argument("--corridors", type=int, default=0)
    ap.add_argument("--barrier", action="store_true")
    ap.add_argument("--braess-diagonal", action="store_true")
    ap.add_argument("--perturb", type=float, default=0.0)
    ap.add_argument("--congestion", default="medium",
                    choices=["low", "medium", "high"])
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    out = Path(a.out) if a.out else root / "tapbench" / "forge" / (
        a.kind if a.kind != "grid" else
        f"grid{a.n}_{a.pattern}_s{a.seed}")
    if a.kind == "diamond":
        forge_diamond(out, a.demand)
    elif a.kind == "braess":
        forge_braess(out, a.demand, a.with_diagonal)
    else:
        forge_grid(out, a.n, a.pattern, a.origins, a.dests_per_origin,
                   a.corridors, a.barrier, a.braess_diagonal, a.perturb,
                   a.congestion, a.seed)


if __name__ == "__main__":
    main()
