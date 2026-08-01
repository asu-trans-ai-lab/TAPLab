# TAPLab

## An Open Laboratory for Reproducible Traffic Assignment Experiments

TAPLab is a software-neutral platform for constructing, validating, visualizing, solving, and comparing traffic assignment problems across different networks, algorithms, and modeling systems.

Unlike a conventional benchmark repository, TAPLab supports the complete experimentation lifecycle:

1. Standardize network and demand inputs.
2. Validate mathematical and data invariants.
3. Visualize networks, zones, connectors, demand, and results.
4. Execute multiple traffic-assignment algorithms through solver adapters.
5. Normalize solver outputs onto common link and node identifiers.
6. Compare convergence, accuracy, runtime, memory, and solution structure.
7. Reproduce and independently verify published computational results.

TAPLab uses compact GMNS-compatible tables as its portable exchange layer while allowing every algorithm to retain its native implementation and internal data structures.

> Note on naming: "TAP Lab" is also the name of Cornell's Transportation Access
> and Policy Lab. This project is unrelated; always cite it with its full
> subtitle, *TAPLab: An Open Laboratory for Reproducible Traffic Assignment
> Experiments*, hosted by the ASU Transportation+AI Lab.

---

## Core Components

| Component | Where | Role |
| --- | --- | --- |
| **TAPBench** | `tapbench/` | Tiered benchmark instances, reference solutions, experiment configurations, and evaluation protocols. |
| **TAPRunner** | `taplab/adapters/`, `taplab run` / `taplab bench` | A common execution interface for Frank–Wolfe, Algorithm B, origin-based, bush-based, path-based, and other solvers. |
| **TAPValidate** | `taplab/validate.py`, `taplab/stats.py` | Validator for network integrity, OD demand, assignment feasibility, and cross-solver consistency; publishes computed network statistics. |
| **TAPView** | `taplab/view.py`, `taplab view` | Interactive TAP-specific network viewer: centroid / connector / physical layers, v/c and volume rendering, solver-difference overlays, per-link inspection across solvers. |
| **TAPDashboard** | `taplab/dashboard.py`, `taplab dashboard` | Static HTML dashboard comparing algorithms, convergence histories, computational performance, and reproducibility status. |
| **TAPForge** | `taplab/forge.py`, `taplab forge` | Parametric instance generator: analytical networks (diamond, Braess), Manhattan grids with corridors / barriers / Braess diagonals, O x D factorials, seeded perturbations — every manifest reproduces its instance. |
| **TAPReports** | `taplab/reports.py` | Normalized run / comparison / experiment reports and the independent reproduce check. |

---

## Benchmark Networks

| Network | Tier | Primary purpose | Status |
| --- | --- | --- | --- |
| Two-route diagnostic | Diagnostic | Unit testing with an analytical equilibrium | Bundled |
| Sioux Falls | Small | Unit testing, debugging, reference verification | Bundled with best-known flows |
| Anaheim | Small–medium | Classical equilibrium and algorithm testing | Bundled with best-known flows |
| Chicago Sketch | Intermediate | Cross-solver verification | Bundled with best-known flows |
| Chicago Regional | Large | Performance and path-coverage analysis | Bundled (gzipped demand) with reference volumes |
| Philadelphia | Large | Scalability and transferability testing | Bundled (gzipped demand) |
| TAPForge A0–A3 | Diagnostic–controlled | Analytical correctness (Braess reproduces exactly) and route-rich latent-atom experiments | Bundled (`tapbench/forge/`) |
| Washington DC driving | City, real OSM | Real topology: one-ways, connectors, SCC restriction | Bundled; certified with tap-b at 4.4e-6 |
| Washington DC transit | City, multimodal | GTFS service network (WMATA + Circulator + Streetcar), TAZ access links, synthetic transit OD | Bundled (track C1) |
| ARC Atlanta super-600 | Regional, simple mode | Physics-informed validation against agency reference volumes | Import via `import_arc_super600` (licensed data, never bundled) |

Exact network statistics are never hard-coded in documentation. TAPValidate computes and publishes them directly from each imported instance:

```bash
taplab stats chicago_sketch     # writes network_statistics.json
```

Reported statistics include physical and centroid node counts, links, connectors, zones, positive-demand OD pairs, total demand by class and period, network density, free-flow-time / capacity / BPR parameter distributions, disconnected OD pairs, zero- or missing-capacity links, invalid connector links, and OD coverage.

Chicago Regional requires a specific distinction among (1) solver accuracy on the supplied path pool, (2) adequacy of the supplied path pool, and (3) convergence to full-network user equilibrium. A fixed-pool solution cannot be described as a full-network equilibrium when positive-demand OD pairs have no available path; TAPLab therefore reports OD coverage and route-richness statistics separately from solver convergence.

---

## Compact Network Representation

Zones are represented by centroid nodes in `node.csv`:

```csv
node_id,node_type,x_coord,y_coord
1,centroid,-87.7100,41.8800
2,centroid,-87.6900,41.8900
101,intersection,-87.7040,41.8820
102,intersection,-87.6980,41.8860
```

Centroid connectors are represented in `link.csv`:

```csv
link_id,from_node_id,to_node_id,link_type,directed,allowed_uses
1,1,101,centroid_connector,0,auto
2,2,102,centroid_connector,0,auto
101,101,102,arterial,1,auto
```

Demand references the same centroid identifiers:

```csv
o_zone_id,d_zone_id,volume,period,agent_type
1,2,1250,AM,auto
2,1,980,AM,auto
```

Operational rules: prefer `node_id = zone_id` for centroids; a connector touches exactly one centroid; connectors are access links, not network shortcuts; a separate zone polygon file is optional and required only for visualization, socioeconomic attributes, spatial aggregation, or connector-generation experiments.

Each instance folder contains `manifest.yml`, `node.csv`, `link.csv`, `demand.csv`, `settings.yml`, `README.md`, `optional/`, and `reference/` with best-known or agency reference outputs.

---

## Solver Library

TAPLab uses a registry-based design (`schemas/solver_registry.json`). Solver source code is neither duplicated nor modified: each adapter identifies the native executable, input conversion, parameter file, execution command, and output parser. Executable locations are supplied per machine through environment variables (`TAPLAB_TAPB_EXE`, `TAPLAB_TAPLITE_EXE`, ...).

| Family | Solver or algorithm | Source | Integration status |
| --- | --- | --- | --- |
| Link-based | Frank–Wolfe (pure Python) | built-in `reference_fw` | Verified (reproducibility anchor) |
| Bush-based | Dial's Algorithm B | `tap-b` | End-to-end verified |
| Path-based | Adaptive-column GP (`latent_gp --algorithm p0`) | built-in | Verified (Sioux Falls certified 9.6e-7; Anaheim 0.24% RMSE vs best-known) |
| Compressed path | Latent-atom GP (`latent_gp --algorithm ol1`) | built-in | Verified; major columns + one latent atom per OD |
| Link-based | MSA, FW, CFW, BFW | `tap-b` | Adapter pathway available |
| Link-based | Frank–Wolfe | TAPLite | Registered (adapter present, not yet verified) |
| Link-based | MSA, FW, CFW, BFW | AequilibraE | Registered (`pip install taplab[full]`, not yet verified) |
| Bush/origin-based | TAPAS | TAsK | Planned (trips parser fix pending) |
| Origin-based | LUCE | TAsK | Planned (trips parser fix pending) |
| Path-based | Gradient Projection | TAsK | Planned (trips parser fix pending) |
| Bush-based | Algorithm B, BFW | TAsK | Planned (trips parser fix pending) |
| Bush-based | iTAPAS | Open-TNM | Planned |
| Other advanced methods | ALM-Greedy, C-BiTA, Greedy | Open-TNM | Planned |
| Origin-bush | O0 fixed-bush Newton | `origin_bush_latent_cpp` | External research lane (controlled grid harness) |
| Path-based | P0 explicit-path GP | `origin_bush_latent_cpp` | Ported natively as `latent_gp` |
| Compressed origin-bush | OL1 latent-atom method | `origin_bush_latent_cpp` | Ported natively as `latent_gp` |

The initial verified computational pathway is:

```text
GMNS
  → TNTP conversion
  → tap-b Algorithm B
  → native solver output
  → GMNS link identifiers
  → user-equilibrium verification
```

On Chicago Sketch, this pathway preserves all 2,950 links and the total OD demand through the GMNS–TNTP round trip. The returned Algorithm B solution is certified by the independent validator at a recomputed relative gap of 2.9e-7, its total system travel time agrees with the independent Frank–Wolfe reference within 0.005%, and its link flows sit within 0.97% RMSE (of mean link flow) of the published best-known solution. On Anaheim the same pathway certifies at a recomputed gap of 5.1e-7 with 0.31% flow RMSE against the best-known solution, and on Chicago Regional at 5.6e-5 in 270 seconds. The TAsK adapters require one remaining parser correction so that generated TNTP trip tables exactly match TAsK's expected spacing and formatting.

---

## Command-Line Workflow

```bash
# Compute benchmark statistics
taplab stats tapbench/chicago_sketch

# Validate the network and demand
taplab validate tapbench/chicago_sketch

# Run Algorithm B
taplab run chicago_sketch --solver tapb

# Run the built-in Frank-Wolfe reference
taplab run chicago_sketch --solver reference_fw

# Run a solver battery and build the comparison dashboard
taplab bench chicago_sketch --solvers reference_fw,tapb

# Compare completed results
taplab compare chicago_sketch --solvers reference_fw,tapb

# Perturbation experiments (demand / capacity scaling)
taplab experiment sioux_falls --demand-scale 0.8,1.0,1.2

# Open the dashboard (static HTML; no server required)
taplab dashboard chicago_sketch

# Interactive network + assignment viewer (static HTML; no server required)
taplab view chicago_sketch

# Independently certify a solver run: recomputed costs, Beckmann objective,
# conservation, shortest-path lower bound, relative gap
taplab verify chicago_sketch --solver tapb --gap-target 1e-4

# Forge controlled instances (parameters + seed recorded in the manifest)
taplab forge braess
taplab forge grid --n 12 --pattern uniform --origins 4 --dests-per-origin 4     --corridors 2 --barrier --braess-diagonal --perturb 0.01 --seed 7

# Independently re-verify an instance's reference outputs
taplab reproduce tapbench/sioux_falls
```

---

## Standard Output Contract

Every run produces, under `results/<instance>/<solver>/`:

```text
summary.json           # solver, algorithm, iterations, gap, runtime, TSTT
convergence.csv        # iteration, relative_gap, wall_time_s
link_performance.csv   # normalized onto GMNS link identifiers
report.md              # TAPReports run report incl. reference comparison
validation_report.json # independent certification from `taplab verify`
```

plus `network_statistics.json` (from `taplab stats`) and `dashboard.html`
(from `taplab dashboard`). Optional algorithm-specific outputs (path flows,
bush links, origin statistics, column-pool statistics) support research
diagnostics but are not required for basic cross-solver comparison.

---

## Repository Structure

```text
TAPLab/
├── README.md, LICENSE, CITATION.cff, CONTRIBUTING.md, pyproject.toml
├── taplab/
│   ├── cli.py              # stats | validate | run | bench | compare | experiment | dashboard | reproduce
│   ├── instance.py         # compact-GMNS instance model
│   ├── validate.py         # TAPValidate level-1/2 invariants
│   ├── stats.py            # TAPValidate computed network statistics
│   ├── experiment.py       # perturbation grids
│   ├── reports.py          # TAPReports
│   ├── dashboard.py        # TAPDashboard (static HTML)
│   ├── view.py             # TAPView interactive network viewer
│   ├── adapters/           # TAPRunner solver adapters
│   └── converters/         # GMNS <-> TNTP, ARC importer
├── schemas/solver_registry.json
├── tapbench/               # diagnostic | sioux_falls | chicago_sketch | import stubs
├── tests/
└── results/                # generated; not version-controlled
```

---

## Central Scientific Contribution

TAPLab is not another traffic-assignment algorithm and is not simply a GMNS conversion package. It provides shared experimental infrastructure for determining whether different traffic-assignment algorithms solve the same mathematical problem, satisfy the same feasibility and equilibrium conditions, and deliver comparable results under transparent computational settings.

Its innovation is the integration of portable problem definitions; tiered small-to-regional benchmark networks; link-, path-, origin-, and bush-based algorithms; standardized solver adapters; mathematical and data validators; network and result visualization; convergence and scalability dashboards; and independently reproducible computational records.

GMNS provides the exchange representation, while TAPLab provides the scientific experimentation, verification, and comparison environment. Every published accuracy figure is certified by the independent validator (`taplab verify`), which recomputes link costs, the Beckmann objective, flow conservation, the shortest-path lower bound, and the relative gap without trusting the solver.

See [ROADMAP.md](ROADMAP.md) for the sequenced plan (time-to-verified-accuracy benchmarking, adaptive KSP-GP, the C++ `libtapcore` kernel, and staged extensions beyond TAP) and [tapbench/DATA_LICENSES.md](tapbench/DATA_LICENSES.md) for per-dataset provenance, citations, and checksums.
