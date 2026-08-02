"""Origin-flow atom laboratory (implements ORIGIN_ATOM_SPEC.md, confirmed).

The object: an origin atom H_o^j is a COMPLETE feasible origin-flow template
(a point of F_o = {x >= 0 : Nx = b_o}) serving all destinations of origin o.
The latent state is x^o = sum_j lambda_j H_j on the per-origin simplex, so
every weight update is feasible by construction.

Three arms on a single-origin, many-destination monotone (DAG) grid:

  B0  full origin/bush worker: per sweep, topological min-cost DP and
      max-used-path DP; per destination, Newton shift from the max-cost used
      path to the min-cost path (diagonal denominator over the symmetric
      difference), Gauss-Seidel cost refresh — the O0 rule generalized
  L1  fixed origin atoms: J atoms primed by perturbed-cost short-B0 runs
      (G2: c_a (1 + eps), eps ~ U(-0.15, 0.15) seeded), then latent gradient
      on lambda only
  L2  adaptive origin atoms: latent gradient until the full-space gap stalls
      (<1% improvement over 5 sweeps), then ONE B0-oracle call (2 sweeps from
      the current x) mints a new atom; prune lambda < 1e-6; oracle cap

The certificate is always the FULL-space relative gap from the topological
shortest-path DP — never the latent-simplex gap. The research question per
the spec: can L2 reach B0-level objective / flows / gap with significantly
fewer full bush sweeps?
"""
from __future__ import annotations

import random
import time
from collections import defaultdict, deque

import numpy as np


class OriginProblem:
    def __init__(self, instance):
        cents = instance.centroids()
        cent_nodes = set(cents.values())

        dem = defaultdict(float)
        for r in instance.demand:
            v = float(r["volume"])
            if v > 0:
                dem[(int(float(r["o_zone_id"])),
                     int(float(r["d_zone_id"])))] += v
        origins = {o for (o, d) in dem}
        assert len(origins) == 1, "origin-atom lab requires a single origin"
        oz = origins.pop()
        self.origin = cents[oz]
        self.dests = {cents[d]: q for (o, d), q in dem.items() if d in cents}
        self.q_total = sum(self.dests.values())
        dest_nodes = set(self.dests)

        # keep only arcs that can lie on an origin->destination path:
        # centroid tails other than the origin and centroid heads other than
        # destinations (e.g. reverse connectors) would create 2-cycles
        arcs, self.fftt, self.cap, self.al, self.be = [], [], [], [], []
        for r in instance.links:
            a = int(float(r["from_node_id"]))
            b = int(float(r["to_node_id"]))
            if (a in cent_nodes and a != self.origin) or \
               (b in cent_nodes and b not in dest_nodes):
                continue
            fs = float(r.get("free_speed") or 30) or 30
            fftt = float(r.get("vdf_fftt") or 0) or float(r["length"]) / fs * 60.0
            arcs.append((a, b))
            self.fftt.append(fftt)
            self.cap.append(max(float(r.get("capacity") or 1), 1e-9))
            self.al.append(float(r.get("vdf_alpha") or 0.15))
            self.be.append(float(r.get("vdf_beta") or 4.0))
        self.arcs = arcs
        self.fftt = np.array(self.fftt)
        self.cap = np.array(self.cap)
        self.al = np.array(self.al)
        self.be = np.array(self.be)
        self.m = len(arcs)

        # topological order (Kahn) — the network must be a DAG
        fwd = defaultdict(list)
        indeg = defaultdict(int)
        nodes = set()
        for i, (a, b) in enumerate(arcs):
            fwd[a].append((b, i))
            indeg[b] += 1
            nodes.update((a, b))
        Q = deque(n for n in nodes if indeg[n] == 0)
        order = []
        while Q:
            u = Q.popleft()
            order.append(u)
            for v, _ in fwd[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    Q.append(v)
        assert len(order) == len(nodes), "network is not a DAG"
        self.topo = order
        self.fwd = fwd

    def times(self, x):
        r = np.maximum(x, 0.0) / self.cap
        t = self.fftt * (1.0 + self.al * r ** self.be)
        tp = np.where(self.be != 1.0,
                      self.fftt * self.al * self.be / self.cap
                      * r ** (self.be - 1.0),
                      self.fftt * self.al / self.cap)
        return t, tp

    def sp_min(self, t):
        dist = {self.origin: 0.0}
        pred = {}
        for u in self.topo:
            if u not in dist:
                continue
            du = dist[u]
            for v, li in self.fwd[u]:
                nd = du + t[li]
                if nd < dist.get(v, np.inf) - 1e-15:
                    dist[v] = nd
                    pred[v] = li
        return dist, pred

    def sp_max_used(self, t, x, eps=1e-9):
        dist = {self.origin: 0.0}
        pred = {}
        for u in self.topo:
            if u not in dist:
                continue
            du = dist[u]
            for v, li in self.fwd[u]:
                if x[li] <= eps:
                    continue
                nd = du + t[li]
                if nd > dist.get(v, -np.inf) + 1e-15:
                    dist[v] = nd
                    pred[v] = li
        return dist, pred

    def path_of(self, pred, d):
        p, u = [], d
        while u != self.origin:
            li = pred.get(u)
            if li is None:
                return None
            p.append(li)
            u = self.arcs[li][0]
        return p

    def full_gap(self, x):
        t, _ = self.times(x)
        dist, _ = self.sp_min(t)
        tstt = float(t @ np.maximum(x, 0.0))
        sptt = sum(dist.get(d, 0.0) * q for d, q in self.dests.items())
        return (tstt - sptt) / max(sptt, 1e-12), t

    def beckmann(self, x):
        r = np.maximum(x, 0.0) / self.cap
        return float(np.sum(self.fftt * x + self.fftt * self.al * self.cap
                            / (self.be + 1.0) * r ** (self.be + 1.0)))

    # ---- B0: the origin/bush worker ------------------------------------
    def init_aon(self, fftt=None):
        t = self.fftt if fftt is None else fftt
        dist, pred = self.sp_min(t)
        x = np.zeros(self.m)
        for d, q in self.dests.items():
            for li in self.path_of(pred, d) or []:
                x[li] += q
        return x

    def b0_sweep(self, x):
        """One equilibration sweep; returns shifts performed."""
        shifts = 0
        for d, q in sorted(self.dests.items(), key=lambda kv: -kv[1]):
            t, tp = self.times(x)
            dmin, pmin = self.sp_min(t)
            dmax, pmax = self.sp_max_used(t, x)
            if d not in dmax or d not in dmin:
                continue
            gap = dmax[d] - dmin[d]
            if gap <= 1e-12:
                continue
            P_min = set(self.path_of(pmin, d) or [])
            P_max = set(self.path_of(pmax, d) or [])
            up = P_min - P_max
            down = P_max - P_min
            if not down:
                continue
            h = float(sum(tp[li] for li in up | down))
            step = min(gap / max(h, 1e-12),
                       min(x[li] for li in down))
            if step <= 0:
                continue
            for li in up:
                x[li] += step
            for li in down:
                x[li] -= step
            shifts += 1
        return shifts

    def b0_solve(self, x=None, tol=1e-5, max_sweeps=2000, history=None,
                 t_offset=0.0, sweeps_offset=0):
        if x is None:
            x = self.init_aon()
        t0 = time.time()
        sweeps = 0
        gap, _ = self.full_gap(x)
        while gap > tol and sweeps < max_sweeps:
            self.b0_sweep(x)
            sweeps += 1
            gap, _ = self.full_gap(x)
            if history is not None:
                history.append(dict(bush_sweeps=sweeps_offset + sweeps,
                                    time_s=t_offset + time.time() - t0,
                                    gap=gap))
        return x, gap, sweeps, time.time() - t0


def prime_atoms(P: OriginProblem, J, prime_sweeps=6, seed=1, eps=0.15):
    """G2 priming: perturbed free-flow costs, short congested B0 runs."""
    rng = random.Random(seed)
    atoms = []
    total_sweeps = 0
    for j in range(J):
        pert = np.array([1 + eps * (2 * rng.random() - 1)
                         for _ in range(P.m)])
        saved = P.fftt
        P.fftt = saved * pert
        x = P.init_aon()
        for _ in range(prime_sweeps):
            P.b0_sweep(x)
        P.fftt = saved
        atoms.append(x.copy())
        total_sweeps += prime_sweeps
    return atoms, total_sweeps


def latent_sweeps(P, atoms, lam, x, n_sweeps, history, t0, bush_sweeps,
                  t_offset, tol):
    """Latent gradient on lambda: dearest positive-weight atom -> cheapest,
    Newton step over the atom-difference curvature. Full-space certificate."""
    q = P.q_total
    for s in range(n_sweeps):
        t, tp = P.times(x)
        costs = [float(H @ t) for H in atoms]
        order = np.argsort(costs)
        l = int(order[0])
        moved = False
        for h in reversed(order):
            h = int(h)
            if h == l or lam[h] <= 1e-12:
                continue
            g = costs[h] - costs[l]
            if g <= 1e-12:
                continue
            diff = atoms[l] - atoms[h]
            curv = float(tp @ (diff * diff))
            step = min(lam[h], g / max(curv, 1e-12))
            if step <= 0:
                continue
            lam[h] -= step
            lam[l] += step
            x += step * diff
            moved = True
            t, tp = P.times(x)
            costs = [float(H @ t) for H in atoms]
            order = np.argsort(costs)
            l = int(order[0])
        gap, _ = P.full_gap(x)
        history.append(dict(bush_sweeps=bush_sweeps,
                            time_s=t_offset + time.time() - t0, gap=gap))
        if gap < tol or not moved:
            break
    return x, lam


def run_L1(P, J, tol=1e-5, max_latent=400, seed=1):
    hist = []
    t0 = time.time()
    atoms, prime_used = prime_atoms(P, J, seed=seed)
    lam = np.full(J, 1.0 / J)
    x = sum(l * H for l, H in zip(lam, atoms))
    x, lam = latent_sweeps(P, atoms, lam, x, max_latent, hist, t0,
                           prime_used, 0.0, tol)
    gap, _ = P.full_gap(x)
    return dict(x=x, gap=gap, atoms=len(atoms), bush_sweeps=prime_used,
                oracle_calls=0, time_s=time.time() - t0, history=hist,
                obj=P.beckmann(x))


def run_L2(P, J0=2, tol=1e-5, oracle_sweeps=2, oracle_cap=12,
           stall_window=5, stall_frac=0.01, max_rounds=60, seed=1):
    hist = []
    t0 = time.time()
    atoms, bush_used = prime_atoms(P, J0, seed=seed)
    lam = np.full(len(atoms), 1.0 / len(atoms))
    x = sum(l * H for l, H in zip(lam, atoms))
    oracle_calls = 0
    for _round in range(max_rounds):
        x, lam = latent_sweeps(P, atoms, lam, x, 50, hist, t0, bush_used,
                               0.0, tol)
        gap, _ = P.full_gap(x)
        if gap < tol:
            break
        recent = [h["gap"] for h in hist[-stall_window:]]
        stalled = len(recent) >= stall_window and \
            recent[-1] > (1 - stall_frac) * recent[0]
        if not stalled and _round > 0:
            continue
        if oracle_calls >= oracle_cap:
            break
        # B0 oracle: mint a new feasible origin response from the current x
        xa = x.copy()
        for _ in range(oracle_sweeps):
            P.b0_sweep(xa)
        bush_used += oracle_sweeps
        oracle_calls += 1
        atoms.append(xa)
        lam = np.append(lam, 0.0)
        keep = lam > 1e-6
        keep[-1] = True
        if not keep.all():
            atoms = [a for a, k in zip(atoms, keep) if k]
            lam = lam[keep]
            lam /= lam.sum()
            x = sum(l * H for l, H in zip(lam, atoms))
        gap, _ = P.full_gap(x)
        hist.append(dict(bush_sweeps=bush_used,
                         time_s=time.time() - t0, gap=gap))
    gap, _ = P.full_gap(x)
    return dict(x=x, gap=gap, atoms=len(atoms), bush_sweeps=bush_used,
                oracle_calls=oracle_calls, time_s=time.time() - t0,
                history=hist, obj=P.beckmann(x))
