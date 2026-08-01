# Contributing to TAPLab

## Adding a benchmark instance
Create `tapbench/<name>/` with `node.csv`, `link.csv`, `demand.csv`,
`settings.yml`, `manifest.yml`, and `README.md` following the compact
GMNS-compatible representation (centroids as `node_type=centroid` rows;
connectors typed `centroid_connector`). Include `reference/` outputs where a
best-known or agency reference solution exists. Never hard-code statistics in
the README; `taplab stats` computes them. Licensed data must not be committed
— contribute an importer under `taplab/converters/` instead (see
`import_arc_super600.py`).

## Adding a solver adapter
Add `taplab/adapters/<name>.py` exposing
`solve(instance, algorithm=..., gap=..., max_time=...) -> dict` with keys
`flows` (list of `{from_node_id, to_node_id, volume, travel_time}` on GMNS
identifiers), `convergence` (list of `(iteration, relative_gap, wall_time_s)`),
and `summary`. Register it in `taplab/adapters/__init__.py` and describe it in
`schemas/solver_registry.json`. Locate native executables through a
`TAPLAB_<NAME>_EXE` environment variable; do not commit binaries or solver
source.

## Tests
`python tests/test_smoke.py` must pass. Add a diagnostic-instance check when
adapter behavior can be verified analytically (see the two-route instance).
