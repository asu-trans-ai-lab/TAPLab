"""TAPAdapter: TAsK framework (Perederieieva et al.) — TAPAS, LUCE, GP,
Algorithm B, BFW, PE on TNTP inputs.

Set TAPLAB_TASK_EXE to task.exe and TAPLAB_TASK_PARAMS_DIR to the folder of
per-algorithm parameter templates (cs_B.params etc.); the adapter clones a
template, rewires NETWORK / OD_MATRIX / LINK_FLOWS / PRECISION / TIME_LIMIT,
and parses the link-flows output back onto GMNS identifiers.

TAsK's OD reader is whitespace-sensitive: trips tables are rewritten in its
fixed-width layout ("Origin%10d", "%5d :%11.2f;") before the run.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .tapb import _to_tntp

ALG_TEMPLATE = {"B": "cs_B.params", "BFW": "cs_BFW.params",
                "GP": "cs_GP.params", "LUCE": "cs_LUCE.params",
                "TAPAS": "cs_TAPAS.params", "PE": "cs_PE.params"}


def _task_style_trips(path: Path):
    """Rewrite a generated TNTP trips file in TAsK's fixed-width layout."""
    txt = path.read_text()
    head, body = txt.split("<END OF METADATA>")
    out = [head.rstrip() + "\n<END OF METADATA>\n\n"]
    for line in body.splitlines():
        m = re.match(r"\s*Origin\s+(\d+)", line)
        if m:
            out.append(f"\nOrigin{int(m.group(1)):>10}\n")
            continue
        pairs = re.findall(r"(\d+)\s*:\s*([\d.eE+-]+)\s*;", line)
        if pairs:
            row = "".join(f"{int(d):>5} :{float(v):>11.2f}; "
                          for d, v in pairs)
            out.append(row + "\n")
    path.write_text("".join(out))


def solve(instance, algorithm="TAPAS", gap=1e-6, max_time=600):
    exe = os.environ.get("TAPLAB_TASK_EXE")
    if not exe or not Path(exe).exists():
        raise RuntimeError("set TAPLAB_TASK_EXE to the TAsK task.exe")
    tdir = os.environ.get("TAPLAB_TASK_PARAMS_DIR") or \
        str(Path(exe).parent / "params")
    alg = algorithm.upper()
    if alg not in ALG_TEMPLATE:
        raise RuntimeError(f"TAsK adapter supports {sorted(ALG_TEMPLATE)}")
    template = Path(tdir) / ALG_TEMPLATE[alg]
    if not template.exists():
        raise RuntimeError(f"params template not found: {template}")

    work = Path(tempfile.mkdtemp(prefix="taplab_task_"))
    name = instance.path.name
    inv = _to_tntp(instance, work, name)
    net = work / "net" / f"{name}_net.txt"
    trips = work / "net" / f"{name}_trips.txt"
    _task_style_trips(trips)
    flows_out = work / "flows.txt"

    params = template.read_text()

    def set_tag(text, tag, value):
        return re.sub(rf"(<{tag}>\s*:\s*)\{{[^}}]*\}}",
                      lambda m: m.group(1) + "{" + value + "}", text)

    params = set_tag(params, "NETWORK", net.as_posix())
    params = set_tag(params, "OD_MATRIX", trips.as_posix())
    params = set_tag(params, "LINK_FLOWS", flows_out.as_posix())
    params = set_tag(params, "PRECISION", f"{gap:g}")
    params = set_tag(params, "TIME_LIMIT", str(int(max_time)))
    pfile = work / "run.params"
    pfile.write_text(params)

    t0 = time.time()
    r = subprocess.run([exe, str(pfile)], cwd=work, capture_output=True,
                       timeout=max_time + 120)
    stdout = (r.stdout or b"").decode("utf-8", "replace")

    flows = []
    if flows_out.exists():
        for line in flows_out.read_text().splitlines():
            p = line.split()
            if len(p) >= 3 and p[0].isdigit() and p[1].isdigit():
                a, b = inv.get(int(p[0])), inv.get(int(p[1]))
                if a is None or b is None:
                    continue
                flows.append(dict(link_id="", from_node_id=a, to_node_id=b,
                                  volume=float(p[2]),
                                  travel_time=float(p[3]) if len(p) > 3 else ""))
    # TAsK convergence lines are bare "<elapsed_s> <gap>" pairs
    conv = []
    for l in stdout.splitlines():
        p = l.split()
        if len(p) == 2 and _is_float(p[0]) and _is_float(p[1]):
            conv.append((len(conv) + 1, float(p[1]), float(p[0])))
    tstt = sum(f["volume"] * f["travel_time"] for f in flows
               if isinstance(f["travel_time"], float)) or None
    return dict(flows=flows, convergence=conv,
                summary=dict(solver="task", algorithm=alg,
                             iterations=len(conv) or None,
                             relative_gap=conv[-1][1] if conv else None,
                             tstt=round(tstt, 2) if tstt else None,
                             wall_time_s=round(time.time() - t0, 2),
                             workdir=str(work)))


def _is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False
