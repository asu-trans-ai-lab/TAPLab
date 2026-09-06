"""TAPAdapter: TAPLite / DTALite kernel (GMNS-native).

Set TAPLAB_TAPLITE_EXE to the kernel executable (bin/TAPLite.exe of the TAPLite4MPO
repository) and optionally TAPLAB_TAPLITE_CONFIG to a folder holding settings.csv /
mode_type.csv templates (the repository ships one at configs/taplab_taplite/).

algorithm -> settings.csv assignment_method:  fw 0 | cfw 1 | bfw 2 | b 3 (origin-based bush)
gap       -> convergence_gap_pct = 100 * gap  (the kernel prints its relative gap in percent)
The kernel stops at the gap or at number_of_iterations (TAPLAB_TAPLITE_MAX_ITERS, default
2000) and runs on TAPLAB_TAPLITE_THREADS processors (default from the template, 8).

What is written into the work folder, because the kernel's readers are narrower than GMNS:
  node.csv   copied as is (the kernel reads node_id, zone_id, x_coord, y_coord);
  link.csv   text link_type values become the integer 1 (the kernel's link_type is an int
             used only for VMT / QVDF reporting); every other column passes through;
  demand.csv exactly o_zone_id,d_zone_id,volume (the kernel reads it with fscanf
             "%d,%d,%lf"; extra GMNS columns would break the parse);
  settings.csv / mode_type.csv from the template folder (or built-in defaults: one class
             'auto', period 7-8 h so hourly capacities apply), with the run overrides above.
Returned: flows from link_performance.csv, the convergence history from the kernel's
convergence_log.csv (iteration, dimensionless gap, wall s) and a summary with the
self-reported final gap, iterations, TSTT (minutes x veh), wall time and peak working set.
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ALGOS = {"fw": 0, "cfw": 1, "bfw": 2, "b": 3, "oba": 3, "bush": 3}
DEFAULT_SETTINGS = [
    ("number_of_iterations", "2000"), ("number_of_processors", "8"),
    ("demand_period_starting_hours", "7"), ("demand_period_ending_hours", "8"),
    ("first_through_node_id", "-1"), ("base_demand_mode", "0"), ("route_output", "0"),
    ("vehicle_output", "0"), ("log_file", "0"), ("odme_mode", "0"), ("odme_vmt", "0"),
    ("demand_format", "0"), ("accessibility_output", "0"), ("convergence_log", "1"),
    ("convergence_gap_pct", "0"), ("convergence_consecutive", "1"), ("assignment_method", "0"),
]
DEFAULT_MODE_TYPE = ("mode_type_id,mode_type,name,vot,pce,occ,demand_file,dedicated_shortest_path\n"
                     "1,auto,AUTO,10,1,1,demand.csv,1\n")


def _read_settings_template(cfg):
    vals = dict(DEFAULT_SETTINGS)
    order = [k for k, _ in DEFAULT_SETTINGS]
    if cfg:
        p = Path(cfg) / "settings.csv"
        if p.exists():
            with open(p, newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            if rows:
                for k, v in rows[0].items():
                    if k and v is not None and v.strip() != "":
                        k = k.strip()
                        vals[k] = v.strip()
                        if k not in order:
                            order.append(k)
    return vals, order


def _write_inputs(instance, work: Path):
    shutil.copy(instance.path / "node.csv", work / "node.csv")
    # link.csv: integer link_type for the kernel, everything else verbatim
    with open(instance.path / "link.csv", newline="", encoding="utf-8-sig") as fh:
        rd = csv.DictReader(fh)
        cols = list(rd.fieldnames or [])
        rows = list(rd)
    # GMNS length here is miles (manifest units length_mi); the kernel reads a bare
    # 'length' as metres, so give it vdf_length_mi unless the instance already does
    add_mi = "vdf_length_mi" not in cols
    if add_mi:
        cols = cols + ["vdf_length_mi"]
    with open(work / "link.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            lt = (r.get("link_type") or "").strip()
            try:
                float(lt)
            except ValueError:
                r["link_type"] = "1"
            if add_mi:
                r["vdf_length_mi"] = r.get("length", "")
            w.writerow(r)
    # demand.csv: the three columns the kernel's fscanf reader expects
    with open(work / "demand.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["o_zone_id", "d_zone_id", "volume"])
        for r in instance.demand:
            v = float(r["volume"] or 0)
            if v > 0:
                w.writerow([int(float(r["o_zone_id"])), int(float(r["d_zone_id"])), repr(v)])


def solve(instance, algorithm="fw", gap=1e-4, max_time=600, max_iterations=None):
    exe = os.environ.get("TAPLAB_TAPLITE_EXE")
    if not exe or not Path(exe).exists():
        raise RuntimeError("set TAPLAB_TAPLITE_EXE to the TAPLite executable")
    alg = (algorithm or "fw").lower()
    if alg not in ALGOS:
        raise RuntimeError("taplite: unknown algorithm %r (fw | cfw | bfw | b)" % algorithm)
    work = Path(tempfile.mkdtemp(prefix="taplab_taplite_"))
    _write_inputs(instance, work)
    cfg = os.environ.get("TAPLAB_TAPLITE_CONFIG")
    vals, order = _read_settings_template(cfg)
    vals["assignment_method"] = str(ALGOS[alg])
    vals["convergence_gap_pct"] = repr(100.0 * float(gap))
    vals["convergence_log"] = "1"
    vals["number_of_iterations"] = str(max_iterations or int(os.environ.get("TAPLAB_TAPLITE_MAX_ITERS", "2000")))
    vals["number_of_processors"] = os.environ.get("TAPLAB_TAPLITE_THREADS", vals.get("number_of_processors", "8"))
    with open(work / "settings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(order)
        w.writerow([vals.get(k, "") for k in order])
    mt = Path(cfg) / "mode_type.csv" if cfg else None
    if mt and mt.exists():
        shutil.copy(mt, work / "mode_type.csv")
    else:
        (work / "mode_type.csv").write_text(DEFAULT_MODE_TYPE)

    t0 = time.time()
    peak = 0
    with open(work / "console.log", "w") as log:
        proc = subprocess.Popen([exe], cwd=work, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
        try:
            import psutil
            ps = psutil.Process(proc.pid)
            deadline = t0 + max_time + 600
            while proc.poll() is None and time.time() < deadline:
                try:
                    mi = ps.memory_info()
                    peak = max(peak, getattr(mi, "peak_wset", mi.rss))
                except psutil.Error:
                    break
                time.sleep(0.05)
            if proc.poll() is None:
                proc.kill()
        except ImportError:
            proc.wait(timeout=max_time + 600)
        rc = proc.wait()
    wall = time.time() - t0

    flows = []
    perf = work / "link_performance.csv"
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
    conv = []
    last = {}
    clog = work / "convergence_log.csv"
    if clog.exists():
        for r in csv.DictReader(open(clog, encoding="utf-8-sig")):
            try:
                it = int(r["iteration_no"])
                g = float(r["gap_pct"]) / 100.0
                conv.append([it, g, float(r.get("wall_s") or 0)])
                last = r
            except (KeyError, ValueError):
                continue
    summary = dict(solver="taplite", algorithm=alg, assignment_method=ALGOS[alg],
                   iterations=int(last["iteration_no"]) if last else None,
                   relative_gap=(float(last["gap_pct"]) / 100.0) if last else None,
                   tstt=float(last["system_tt"]) if last and last.get("system_tt") else None,
                   beckmann_objective=(float(last["beckmann_objective"])
                                       if last and last.get("beckmann_objective") else None),
                   wall_time_s=round(wall, 3), peak_working_set_mb=round(peak / 1048576.0, 1),
                   return_code=rc, workdir=str(work))
    return dict(flows=flows, convergence=conv, summary=summary)
