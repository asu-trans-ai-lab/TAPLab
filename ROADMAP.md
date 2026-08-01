# TAPLab roadmap

Sequenced from the 2026-07 external review. Correctness items from that
review already landed in v0.3: TNTP `<FIRST THRU NODE>` centroid handling
(verified on Anaheim: flow RMSE vs best-known fell from 72% to 0.31%),
authoritative `vdf_fftt` preserved through both converter directions,
GMNS directionality canonicalized into explicit directed arcs, `link_id`
attached to solver outputs, the independent solution validator
(`taplab verify`), honest adapter statuses, failure rows in bench results,
and per-dataset provenance with checksums.

## 1. Benchmark methodology (next)

- **Time-to-verified-accuracy** as the headline metric: runtime until the
  *independently recomputed* relative gap (from `taplab verify`) meets common
  targets 1e-2 / 1e-4 / 1e-6 — not until each solver's private stopping rule
  fires. General principles: Beiranvand, Hare & Lucet (2017); instance
  selection and failure-aware reporting: MIPLIB 2017.
- **Run manifest** per run: commit, executable hash, compiler and flags, CPU,
  OS, threads, seed, exact command, input checksums.
- **Work counters**: iterations, shortest-path calls, line searches, flow
  shifts; path work (generated / active paths, path-link nonzeros, pricing
  calls) for path-based methods.
- **Performance profiles** (Dolan–Moré) for cross-solver summaries, with
  failures and timeouts included, instead of averaged runtimes.
- **Benchmark lanes** kept separate: single-thread deterministic; declared
  parallel; solve-only; end-to-end; fixed path pool; unrestricted
  full-network UE. Never mix hardware in a raw runtime ranking.

## 2. Path-based engine: adaptive KSP-GP

Three explicitly different modes:

1. **Static KSP**: K loopless free-flow-cost paths, restricted-master solve;
   K sweep over {1, 2, 4, 8, 16, 32} reporting OD coverage, path overlap,
   detour ratios, pool size, restricted-master gap AND full-network gap.
2. **Common-pool comparison**: identical path pool for every inner solver
   (GP, Newton, projected gradient, latent); deep classical GP on the same
   pool is the reference. Tests the optimizer, not path discovery.
3. **Adaptive KSP / column generation** (the main engine): restricted-master
   solve, network-wide pricing against current shortest paths, add columns
   beyond a pricing tolerance, repeat until the independently computed
   network gap meets target. A small restricted-master gap never certifies
   pool adequacy — only pricing does. Diversity controls on generation
   (max overlap, max detour ratio, looplessness, deduplication);
   origin-batched pricing and sparse incidence for Chicago Regional and
   Philadelphia (never materialize K paths per OD upfront).

## 3. Engine architecture: Python orchestration + C++ kernel

One design, not two implementations. Python owns I/O, schemas, orchestration,
independent validation, reporting, and small readable reference solvers.
A `libtapcore` C++ kernel (pybind11) owns: CSR directed network, BPR cost /
derivative / integral, Dijkstra and KSP, AON loading, FW/MSA, sparse path
pools, path-based GP, adaptive pricing, deterministic work counters.
Cross-engine tests compare Python and C++ at equal tolerance (objective, gap,
flows, feasibility — not bitwise floats) on: two-route, Sioux Falls,
parallel-link and asymmetric directed cases, centroid no-through constraints,
disconnected OD pairs, randomized small graphs, Chicago Sketch.

## 4. First public release portfolio

Python reference FW; C++ FW and BFW; C++ adaptive KSP-GP; tap-b Algorithm B
adapter (verified); AequilibraE adapter; TAsK TAPAS/LUCE/GP/B/BFW after the
trips parser fix; independent TAPValidate certification on every published
number. Algorithm B (Bar-Gera 2002 lineage via Dial; spartalab/tap-b) sits in
its own origin-based lane — its state and work units differ from fixed-path
methods.

## 5. Beyond TAP (staged; the contract is the reusable idea)

- **TAPLab 1.0**: static traffic assignment only.
- **ColumnBench**: multicommodity flow, cutting stock / set covering, VRPTW —
  reusing path/column pools, pricing, restricted masters (OR-Library,
  CVRPLIB).
- **NetworkDesign**: DNDP, cardinality DNDP, CNDP, interdiction.
- **Scheduling**: crew scheduling, railway timetabling, time-space networks.

The reusable contract is `Problem` / `SolverAdapter` / `Result` /
independent `Evaluator` — unrelated problems are never forced into the TAP
mathematical model.

## Known limitations (current)

- Parallel links between the same node pair are rejected by validation (V2);
  full `link_id`-keyed comparison is the lift that removes this restriction.
- The TAsK trips-table spacing fix is still pending; its adapters are
  `planned`, not `registered`.
- Philadelphia ships without reference flows (track B4 measures scalability,
  not flow reproduction).
- `reference_fw` is deliberately slow (pure Python); large-network baselines
  come from native adapters until the C++ kernel lands.


## 6. TAPForge: the controlled laboratory (from the 2026-07 expansion)

`taplab forge` generates parametric instances; every manifest records the
full parameter set and seed. Implemented: A0 two-route / diamond / Braess
(the paradox reproduces exactly: 82.25 vs 66.00 min at UE), A2/A3 Manhattan
grids with corridors, barriers, Braess diagonals, seeded cost perturbation,
corner/uniform/radial demand, and the |O| x |D_o| factorial
({1,4,16,all} x {1,4,16,all}). First controlled latent-atom result: on the
route-rich grid12 (corridors+barrier+diagonal+perturbation), OL1 converges
faster than explicit P0 (0.24 s vs 0.65 s to ~1e-5) with 63 active columns
vs 195 after folding 525 into 12 atoms; on path-poor Sioux Falls the two are
equivalent — compression pays exactly where the path space is rich.

Planned per the expansion:
- A1 origin-structure factorial as a formal experimental axis; common bush
  representation with `orientation = origin | destination` (LUCE's
  destination-oriented bushes via the transposed graph).
- A4/A5 space-time and space-time-state DAG generators (movement, waiting,
  pickup/delivery, charging, transfer, service-state arcs) with topological
  DP as the canonical kernel; balanced designs, never the full Cartesian
  product.
- Kernel policy: label-setting Dijkstra (binary heap) is the canonical
  static kernel; one-to-all per origin; transposed-graph Dijkstra for
  destination orientation; Yen for static KSP; time-dependent label-setting
  for FIFO; topological DP for DAGs; RAPTOR / Connection Scan for
  schedule-based transit; multilabel with dominance for multicriteria
  walk/bike. Two separate experiments: assignment benchmark (fixed kernel)
  vs kernel benchmark (fixed assignment). External executables that cannot
  adopt the kernel are `external_black_box`, compared end-to-end only.
- Work counters per the Xie & Xie origin-based comparison protocol: node
  scans, link relaxations, bush arcs, PAS structures, local node problems,
  flow shifts, represented routes, time-to-each-verified-gap — runtime alone
  cannot compare LUCE / B / TAPAS / iTAPAS fairly.
- Latent-atom experiment ladder (8 arms): full explicit GP; major-only;
  random grouping baseline; geometry route-family atoms;
  signature-preserving atoms; major-latent with first-order refinement;
  with quadratic refinement; with adaptive promotion/splitting. Restricted-
  pool accuracy evaluates the representation; full-space first-order pricing
  remains the certificate.
- B1 canonical track additions from TransportationNetworks: Winnipeg,
  Eastern Massachusetts, Austin; C1 schedule-based transit as a routing /
  column-generation track first (time-expanded DP + RAPTOR oracles), with
  capacity/crowding feedback as a later assignment model.
