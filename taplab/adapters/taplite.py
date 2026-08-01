"""TAPAdapter: TAPLite / DTALite kernel (GMNS-native).
Set TAPLAB_TAPLITE_EXE (and optionally TAPLAB_TAPLITE_CONFIG for
settings.csv / mode_type.csv templates)."""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def solve(instance, algorithm="fw", gap=1e-4, max_time=600):
    exe = os.environ.get("TAPLAB_TAPLITE_EXE")
    if not exe or not Path(exe).exists():
        raise RuntimeError("set TAPLAB_TAPLITE_EXE to the TAPLite executable")
    work = Path(tempfile.mkdtemp(prefix="taplab_taplite_"))
    for f in ["node.csv", "link.csv", "demand.csv"]:
        shutil.copy(instance.path / f, work / f)
    cfg = os.environ.get("TAPLAB_TAPLITE_CONFIG")
    if cfg:
        for f in Path(cfg).glob("*.csv"):
            shutil.copy(f, work / f.name)
    t0 = time.time()
    subprocess.run([exe], cwd=work, capture_output=True, text=True,
                   timeout=max_time + 600)
    perf = work / "link_performance.csv"
    flows = []
    if perf.exists():
        for r in csv.DictReader(open(perf, encoding="utf-8-sig")):
            try:
                flows.append(dict(
                    from_node_id=int(float(r["from_node_id"])),
                    to_node_id=int(float(r["to_node_id"])),
                    volume=float(r.get("volume") or 0),
                    travel_time=float(r.get("travel_time") or 0)))
            except (KeyError, ValueError):
                continue
    return dict(flows=flows, convergence=[],
                summary=dict(solver="taplite", algorithm=algorithm,
                             wall_time_s=round(time.time() - t0, 2),
                             workdir=str(work)))
