# Origin-Flow Atom: Prototype Specification (for confirmation before coding)

*Internal — not for release. Status: DRAFT awaiting confirmation. Per the
agreed protocol, no experiment code is written against this definition until
it is confirmed.*

## 1. The object being defined

An **origin atom** is NOT a new path and NOT a group of paths compressed into
one number. It is **one complete, feasible flow-assignment template for one
origin o serving ALL of its destinations**.

For origin o with destination demands q_o1, ..., q_oD, Algorithm B's true
variables are the origin-specific link flows x_a^o, a in A. The feasible
region is

    F_o = { x^o >= 0 : N x^o = b_o }

where N is the node-link incidence matrix and b_o carries the origin
injection sum_d q_od and each destination's absorption -q_od. Feasibility
means: full demand emitted, each destination absorbs exactly q_od,
intermediate-node conservation, nonnegativity, and (in practice) support on
an acyclic bush.

An origin atom H_o^j is a **point of F_o** — each atom by itself already
satisfies every OD demand and every conservation constraint. The working
representation is a convex combination

    x^o = sum_j lambda_oj * H_o^j,   lambda_oj >= 0,  sum_j lambda_oj = 1.

The latent worker optimizes the few dozen lambda_oj, never the (potentially
millions of) path flows. Because each atom is feasible and the combination is
convex, **every iterate is feasible by construction** — no OD or conservation
constraint can ever be violated by a weight update.

## 2. What one atom does and does not claim

One atom encodes one complete distribution pattern (e.g., a north-corridor
response vs a south-corridor response), implicitly covering many paths at
fixed internal proportions. It does NOT span the million-path feasible
region: with a single atom (lambda_o1 = 1) there is no degree of freedom at
all. The honest claim is:

> a small set of feasible origin-flow templates approximates the
> high-dimensional feasible region induced by the full path set, with
> **full-space pricing detecting whether an important direction is missing**.

Minimum viable configurations: J in {2, 4, 8, 16} atoms; or explicit major
structure + residual atoms; or one initial atom grown by pricing.

## 3. Distinction from the path-group OL1 (what we have tested so far)

| | OL1 (tested to date) | Origin atom (this spec) |
|---|---|---|
| Unit | per-(O,D): minor paths folded into one weighted path-set column | per-origin: one complete feasible flow template over ALL destinations |
| Feasibility of one unit | carries a share of one OD's demand | satisfies the origin's ENTIRE demand vector by itself |
| Simplex | per-OD over {majors + atom} | per-origin over {atoms}: sum_j lambda_oj = 1 |
| Combines with | path-based GP / restricted masters | Algorithm B / bush workers directly |
| Storage | path-link incidence lists | origin link-flow vector (bush-sparse) |

All results reported so far (latent_gp OL1, column_cpp latent, scenario
reuse) are the LEFT column. Nothing reported so far tests the RIGHT column.
The two must never be conflated in writing; "origin atom" is reserved for
the right column from now on.

## 4. Atom generation (no path enumeration anywhere)

- **G1 — Algorithm B state snapshots.** Run a few B sweeps; save the
  origin-specific link flows at different stages as H_o^1..H_o^J. Each
  snapshot is feasible by construction.
- **G2 — Perturbed-cost priming.** Repeatable link-cost perturbations
  c_a^(j) = c_a (1 + eps_a^(j)), a few bush sweeps each: yields
  north-corridor / south-corridor / bottleneck-avoiding / balanced atoms.
- **G3 — Responsive atoms.** Short B runs under different demand/congestion
  scenarios; cluster the origin responses into a few representative atoms
  (closest to the latent method's real contribution).

## 5. Latent gradient update on atom weights

Atom cost at current link costs: C_oj = sum_a t_a(x_a) H_oa^j. The worker
moves weight from a positive-weight high-cost atom h to the cheapest atom l:

    lambda_oh -= Delta,  lambda_ol += Delta

with Delta from gradient projection or a Newton line search using curvature
sum_a t'_a (H_oa^l - H_oa^h)^2 scaled by total origin demand. Feasibility is
automatic (convex combination of feasible points).

## 6. Integration with Algorithm B (fully-corrective column generation,
where a column is an origin response, not a path)

    Algorithm B / bush oracle
        -> produces a NEW feasible origin-flow pattern
        -> joins the latent master as a new origin atom
        -> latent gradient worker re-optimizes atom weights
        -> full Algorithm B / shortest-path gap certification

Division of labor: B discovers new bushes/branches/directions; the latent
worker redistributes fast among already-discovered origin patterns; full
pricing certifies that the latent convex hull is not missing an important
direction.

## 7. The confirmed experiment (to be coded ONLY after this spec is agreed)

Three arms on one single-origin, many-destination Manhattan grid
(forge one2many; candidate: n=16, D=16 destinations):

- **B0 — Full origin/bush worker**, no latent (the O0 fixed-bush Newton in
  origin_bush_latent is the closest existing implementation).
- **L1 — Fixed origin atoms**: J in {2, 4, 8, 16} atoms from short-B priming
  (G1/G2); optimize lambda only.
- **L2 — Adaptive origin atoms**: when the full gap stalls, call the B
  oracle once for a new atom; continue the latent gradient.

Metrics: relative gap (full-space certified), Beckmann objective, link-flow
error vs B0, origin/bush sweeps, atom count, memory, runtime, and **number
of full B-oracle calls** — because the honest research question is:

> Can L2 reach B0-level objective, link flows, and equilibrium gap with
> SIGNIFICANTLY FEWER full origin-bush sweeps?

— not the presupposition that latent matches B outright.

## 8. Open design choices needing confirmation

1. **Atom storage**: dense m-vector per atom vs bush-sparse (proposal:
   bush-sparse — links with x_a^o > 0 only; grids make dense affordable but
   the design should scale).
2. **Priming recipe for L1**: G1 snapshots (cheapest), G2 perturbed costs
   (more diverse), or both (proposal: G2 with eps ~ U(-0.15, +0.15), J seeds).
3. **L2 oracle trigger**: gap-stall rule (relative-gap improvement < 1% over
   5 latent sweeps) vs fixed schedule (proposal: stall rule, cap on oracle
   calls).
4. **Atom pruning**: drop atoms with lambda < 1e-6 after each oracle call?
   (proposal: yes, keeps J bounded.)
5. **Grid configuration**: n=16 one2many with 16 destinations, medium
   congestion, seed fixed (proposal), or the full A1 factorial from the
   start.
