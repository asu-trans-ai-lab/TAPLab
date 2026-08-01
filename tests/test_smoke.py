"""Smoke tests: validate + solve + reproduce on the bundled Sioux Falls
instance. Run with: python -m pytest tests/ (or python tests/test_smoke.py)."""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from taplab.instance import Instance
from taplab.validate import validate
from taplab.adapters import reference_fw

INST = ROOT / "tapbench" / "sioux_falls"


def test_validate_passes():
    rep = validate(Instance.load(INST))
    assert rep["pass"], rep["errors"]
    assert rep["info"]["zones"] == 24
    assert rep["info"]["links"] == 76
    assert abs(rep["info"]["total_demand"] - 360600.0) < 1e-6


def test_reference_fw_reproduces_summary():
    out = reference_fw.solve(Instance.load(INST), gap=1e-6)
    ref = json.loads((INST / "reference" / "summary.json").read_text())
    assert abs(out["summary"]["tstt"] - ref["tstt"]) < 1.0
    assert out["summary"]["relative_gap"] <= 1e-4


def test_flows_near_best_known():
    import csv
    out = reference_fw.solve(Instance.load(INST), gap=1e-6)
    ours = {(f["from_node_id"], f["to_node_id"]): f["volume"]
            for f in out["flows"]}
    rows = list(csv.DictReader(open(INST / "reference" / "link_performance.csv",
                                    encoding="utf-8-sig")))
    ref = {(int(float(r["from_node_id"])), int(float(r["to_node_id"]))):
           float(r["volume"]) for r in rows}
    rmse = math.sqrt(sum((ours[k] - ref[k]) ** 2 for k in ref) / len(ref))
    mean = sum(ref.values()) / len(ref)
    assert rmse / mean < 0.10, f"RMSE {rmse:.0f} vs mean {mean:.0f}"


def test_two_route_analytical_split():
    """Symmetric parallel routes must split 2,000 trips exactly 50/50."""
    inst = Instance.load(ROOT / "tapbench" / "diagnostic" / "two_route")
    out = reference_fw.solve(inst, gap=1e-8)
    flows = {(f["from_node_id"], f["to_node_id"]): f["volume"]
             for f in out["flows"]}
    assert abs(flows[(1, 2)] - 1000.0) < 0.5, flows
    assert abs(flows[(1, 3)] - 1000.0) < 0.5, flows


def test_latent_gp_two_route_and_sioux():
    """latent_gp (P0/OL1) must hit the analytical split and certify on
    Sioux Falls near the reference TSTT."""
    from taplab.adapters import latent_gp
    inst = Instance.load(ROOT / "tapbench" / "diagnostic" / "two_route")
    out = latent_gp.solve(inst, algorithm="p0", gap=1e-8)
    f = {(r["from_node_id"], r["to_node_id"]): r["volume"] for r in out["flows"]}
    assert abs(f[(1, 2)] - 1000.0) < 0.5 and abs(f[(1, 3)] - 1000.0) < 0.5
    inst = Instance.load(INST)
    out = latent_gp.solve(inst, algorithm="ol1", gap=1e-6, max_time=60)
    s = out["summary"]
    assert s["relative_gap"] < 1e-5, s
    assert abs(s["tstt"] - 7480000) < 5000, s


def test_chicago_sketch_validates():
    rep = validate(Instance.load(ROOT / "tapbench" / "chicago_sketch"))
    assert rep["pass"], rep["errors"]
    assert rep["info"]["zones"] == 387
    assert rep["info"]["links"] == 2950


if __name__ == "__main__":
    test_validate_passes()
    test_reference_fw_reproduces_summary()
    test_flows_near_best_known()
    test_two_route_analytical_split()
    test_chicago_sketch_validates()
    print("all smoke tests pass")
