# ARC Atlanta super-600 (import required)

A simple-mode configuration of the Atlanta Regional Commission (ARC)
activity-based model: the full regional highway network with demand
aggregated to 600 super-zones (SOV, HOV2, HOV3 classes). The ARC model data
is licensed and is NOT bundled in this repository; only the importer is.

To build the instance locally:

    set TAPLAB_ARC_SUPER600_DIR=<path to arc_super_600>
    python -m taplab.converters.import_arc_super600 tapbench/arc_atlanta_super600

Then `taplab stats` / `taplab validate` compute and publish all network
statistics directly from the imported instance. This instance connects TAPLab
to the ARC-Bench benchmark tracks (physics-informed validation of assignment
results against reference volumes).
