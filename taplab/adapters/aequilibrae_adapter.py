"""TAPAdapter: AequilibraE (optional; pip install aequilibrae).
Translates the compact GMNS tables into an in-memory AequilibraE graph
and runs its assignment (bfw, cfw, fw, msa)."""
from __future__ import annotations

import time


def solve(instance, algorithm="bfw", gap=1e-6, max_time=600):
    try:
        import numpy as np
        import pandas as pd
        from aequilibrae.paths import TrafficAssignment, TrafficClass, Graph
        from aequilibrae.matrix import AequilibraeMatrix
    except ImportError as e:
        raise RuntimeError("pip install aequilibrae to use this adapter") from e

    cents = instance.centroids()
    zones = sorted(cents)
    net = pd.DataFrame([
        dict(link_id=i + 1,
             a_node=instance.link_key(r)[0], b_node=instance.link_key(r)[1],
             direction=1,
             capacity=float(r["capacity"]),
             free_flow_time=(float(r.get("vdf_fftt") or 0)
                             or float(r["length"]) / (float(r.get("free_speed") or 30)) * 60),
             alpha=float(r.get("vdf_alpha") or 0.15),
             beta=float(r.get("vdf_beta") or 4.0))
        for i, r in enumerate(instance.links)])

    g = Graph()
    g.network = net
    g.prepare_graph(np.array([cents[z] for z in zones], dtype=np.int64))
    g.set_graph("free_flow_time")
    g.set_blocked_centroid_flows(False)

    mat = AequilibraeMatrix()
    mat.create_empty(zones=len(zones), matrix_names=["matrix"], memory_only=True)
    mat.index[:] = np.array([cents[z] for z in zones], dtype=np.int64)
    zidx = {z: i for i, z in enumerate(zones)}
    for r in instance.demand:
        v = float(r["volume"])
        o, d = int(float(r["o_zone_id"])), int(float(r["d_zone_id"]))
        if v > 0 and o in zidx and d in zidx and o != d:
            mat.matrix["matrix"][zidx[o], zidx[d]] += v
    mat.computational_view(["matrix"])

    tc = TrafficClass("auto", g, mat)
    ta = TrafficAssignment()
    ta.set_classes([tc])
    ta.set_vdf("BPR")
    ta.set_vdf_parameters({"alpha": "alpha", "beta": "beta"})
    ta.set_capacity_field("capacity")
    ta.set_time_field("free_flow_time")
    ta.set_algorithm(algorithm)
    ta.rgap_target = float(gap)
    t0 = time.time()
    ta.execute()
    res = ta.results().reset_index()
    flows = []
    for _, row in res.iterrows():
        flows.append(dict(from_node_id=int(net.loc[net.link_id == row.link_id, "a_node"].iloc[0]),
                          to_node_id=int(net.loc[net.link_id == row.link_id, "b_node"].iloc[0]),
                          volume=float(row.matrix_ab if "matrix_ab" in row else row.get("PCE_AB", 0)),
                          travel_time=""))
    return dict(flows=flows, convergence=[],
                summary=dict(solver="aequilibrae", algorithm=algorithm,
                             relative_gap=float(ta.assignment.rgap),
                             wall_time_s=round(time.time() - t0, 2)))
