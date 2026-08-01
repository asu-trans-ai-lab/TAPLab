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

INST = ROOT / "instances" / "sioux_falls"


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


if __name__ == "__main__":
    test_validate_passes()
    test_reference_fw_reproduces_summary()
    test_flows_near_best_known()
    print("all smoke tests pass")
