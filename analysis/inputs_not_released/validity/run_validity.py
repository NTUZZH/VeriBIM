#!/usr/bin/env python3
"""Engineering-validity analyses of one trained model's edited building models, from one config.

  (A) off-target changes: whole-model difference of every completed output against its ground truth
  (B) absolute centre and dimension errors of the edit targets, and completion under a 1 cm tolerance
  (C) new schema errors and new hard clashes of the outputs against those of the ground truth (Table S6)
  (D) completion under the relation gate, its strict variant, the gate over every stored 108-task arm (and its
      27-arm extension), the 1 cm tolerance (Table S19), and the relaxed reading of the under-specified tasks

Per task the OLD analysis functions run unchanged (vworker.py imports them); the summaries are parameterised copies
of the old summary scripts (oldcopies.py). Number formats and the output layer come from analysis/make_macros.py
(imported, not copied or edited).

Run (absolute paths; cores 8-9, two workers):
    taskset -c 8-9 env OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \\
        python analysis/validity/run_validity.py \\
        --config CONFIG.json [--preflight-only]

Outputs (paths in the config's out block): a LaTeX file of \\Pm... macros, a JSON file with the unformatted values
and the per-task rows behind every count, and the table-row fragments of the proposed model (tab_schema, tab_abserr,
tab_offtarget, tab_gate_all). Raw per-task rows of every analysis stay in out.work_dir (a rerun resumes from them).

Edited models: each row's edited_ifc names <dir>/edited/<task>/<file>. The file is read where it lies when it is on
disk; otherwise it is streamed out of <dir>/edited.tar.gz (member edited/<task>/<file>), one member at a time, into
out.scratch, and deleted as soon as every analysis of that file has returned. An archive listed in the set's
override_archives takes precedence (the stand-in's re-run archive edited_v4e.tar.gz). At no time do the unpacked files
exceed limits.max_unpacked_gb, and nothing is unpacked when the free space would drop below limits.min_free_gb.

Exit codes: 0 done; 2 refused before any analysis (missing input, id mismatch, missing edited model, placeholder,
name collision, disk); 3 analyses ran but some rows failed (no macro file is written; the JSON lists the failures).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import math
import multiprocessing as mp
import os
import re
import shutil
import sys
import tarfile
import time
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))           # analysis: make_macros
sys.path.insert(0, str(HERE))
import make_macros as MM                        # noqa: E402  (main() is guarded; helpers only)
import oldcopies as OC                          # noqa: E402

fail = MM.fail
GenError = MM.GenError
ANALYSES = ("offtarget", "gate", "schema")
SETTOK = dict(MM.SETTOK)


def log(msg):
    print(f"{time.strftime('%F %T')} {msg}", flush=True)


def free_gb(path):
    return shutil.disk_usage(path).free / 1e9


def tree_gb(path):
    """Bytes under a folder, in GB (os.scandir walk; the scratch folder holds few files)."""
    tot, stack = 0, [str(path)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        tot += e.stat(follow_symlinks=False).st_size
        except FileNotFoundError:
            pass
    return tot / 1e9


def mem_available_gb():
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1e6
    return 99.0


# ====================================================================== config and inputs
def load_config(path):
    MM.check_path(os.path.abspath(path), "config")
    cfg = json.load(open(path, encoding="utf-8"))

    def walk(x, where):
        if isinstance(x, dict):
            for k, v in x.items():
                if not k.startswith("_"):
                    walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{where}[{i}]")
        elif isinstance(x, str) and ("<" in x and ">" in x) and not x.startswith("\\"):
            fail(f"config field {where} still holds a placeholder: {x}")
    walk(cfg, "config")
    for k in ("model", "label", "tasks_file", "gold", "sets", "analyses", "out", "limits"):
        if k not in cfg:
            fail(f"config: field {k!r} missing")
    for k in ("tex", "json", "fragments_prefix", "work_dir", "scratch"):
        if not os.path.isabs(cfg["out"].get(k, "")):
            fail(f"config: out.{k} must be an absolute path")
    return cfg


def read_ids(spec, tasks, label):
    if spec == "all":
        return sorted(tasks)
    MM.check_path(spec, label)
    S = json.load(open(spec, encoding="utf-8"))
    MM.register(label, spec, len(S))
    if len(set(S)) != len(S):
        fail(f"{label}: duplicate ids in {spec}")
    bad = [t for t in S if t not in tasks]
    if bad:
        fail(f"{label}: {len(bad)} ids are not in the task file, for example {bad[:3]}")
    return sorted(S)


def read_set_rows(scfg, ids, label):
    """Per-task rows of one set: exactly the expected ids (make_macros.read_per_task), or with slice_of_read the
    expected ids out of a larger read (every expected id must be there)."""
    if not scfg.get("slice_of_read"):
        return MM.read_per_task(scfg["per_task"], ids, label)
    rows = {}
    for p in ([scfg["per_task"]] if isinstance(scfg["per_task"], str) else scfg["per_task"]):
        r = MM.read_jsonl_rows(p, label)
        both = sorted(set(r) & set(rows))
        if both:
            fail(f"{label}: {len(both)} ids occur in more than one file, for example {both[:3]}")
        rows.update(r)
    miss = sorted(set(ids) - set(rows))
    if miss:
        fail(f"{label}: {len(miss)} expected ids are not in the read, for example {miss[:3]}")
    rows = {t: rows[t] for t in ids}
    bad = sorted(t for t, r in rows.items() if not isinstance(r.get("score"), dict) or any(k not in r["score"] for k in MM.AX))
    if bad:
        fail(f"{label}: {len(bad)} rows without a score, for example {bad[:3]}")
    return rows


def declared_exclusions(scfg, label):
    """Tasks whose scored edited model is known to be gone (config 'exclude'): each entry names a CSV file, a filter
    and the id column, plus the reason. They are removed from the set before any analysis and listed in every output."""
    out = {}
    for e in scfg.get("exclude", []):
        MM.check_path(e["csv"], f"{label} exclusion list")
        rows = list(csv.DictReader(open(e["csv"], encoding="utf-8")))
        MM.register(f"{label} exclusion list", e["csv"], len(rows))
        for r in rows:
            if all(r.get(k) == v for k, v in e.get("where", {}).items()):
                out[r[e["column"]]] = e["why"]
    return out


# ====================================================================== edited models: where each one lies
def _norm_member(name):
    return name[2:] if name.startswith("./") else name


def archive_listing(path, work_dir, label):
    """{member: size} of a .tar.gz, cached in work_dir under the archive's path, size and mtime."""
    st = os.stat(path)
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
    cache = Path(work_dir) / f"listing_{label}_{key}.json"
    if cache.is_file():
        d = json.load(open(cache))
        if d["path"] == str(path) and d["size"] == st.st_size and d["mtime_ns"] == st.st_mtime_ns:
            return d["members"]
    log(f"listing {path} ({st.st_size / 1e9:.2f} GB)")
    members = {}
    with tarfile.open(path, "r|gz") as tf:
        for m in tf:
            if m.isfile():
                members[_norm_member(m.name)] = m.size
    tmp = cache.with_suffix(".tmp")
    json.dump({"path": str(path), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "members": members}, open(tmp, "w"))
    os.replace(tmp, cache)
    return members


class Locator:
    def __init__(self, work_dir, label):
        self.work_dir, self.label, self.lists = work_dir, label, {}

    def members(self, arc):
        arc = str(arc)
        if arc not in self.lists:
            self.lists[arc] = archive_listing(arc, self.work_dir, self.label) if os.path.isfile(arc) else None
        return self.lists[arc]

    def resolve(self, row, overrides):
        """('disk', path) | ('tar', archive, member, size) | ('none', why) | ('missing', why)."""
        tid = row["task_id"]
        named = row.get("edited_ifc") or ""
        if not named or row.get("edited_exists") is False:
            return ("none", "the row names no edited model (the run wrote none)")
        P = Path(named)
        member = f"edited/{tid}/{P.name}"
        for arc in overrides:
            mem = self.members(arc)
            if mem is None:
                fail(f"override archive missing: {arc}")
            if member in mem:
                return ("tar", str(arc), member, mem[member])
        if P.is_file() and P.stat().st_size > 0:
            return ("disk", str(P))
        parts = P.parts
        if "edited" not in parts:
            return ("missing", f"{P} is not on disk and its path has no edited/ folder")
        k = len(parts) - 1 - parts[::-1].index("edited")
        arc = Path(*parts[:k]) / "edited.tar.gz"
        mem = self.members(arc)
        if mem is None:
            return ("missing", f"{P} is not on disk and {arc} does not exist")
        if member not in mem:
            return ("missing", f"{P} is not on disk and {member} is not in {arc}")
        return ("tar", str(arc), member, mem[member])


# ====================================================================== the run
class Runner:
    def __init__(self, cfg, cfg_path):
        self.cfg, self.cfg_path = cfg, os.path.abspath(cfg_path)
        self.lim = cfg["limits"]
        self.workers = int(self.lim.get("workers", 2))
        if self.workers > 6:
            fail("limits.workers: at most 6 worker processes (2 on the build cores; more only on cores that are free)")
        self.max_unpacked = float(self.lim.get("max_unpacked_gb", 6)) * 1e9
        self.min_free = float(self.lim.get("min_free_gb", 34))
        self.min_mem = float(self.lim.get("min_mem_gb", 8))
        self.stall_s = float(self.lim.get("stall_minutes", 120)) * 60
        self.scratch = Path(cfg["out"]["scratch"])
        self.work_dir = Path(cfg["out"]["work_dir"])
        self.tag = cfg.get("file_tag", "")
        self.ex = None
        self.unpacked = 0
        self.failed_items = []
        self.stats = {"peak_unpacked_gb": 0.0, "peak_scratch_gb": 0.0, "peak_worker_rss_mb": 0.0, "sets": {}}

    # ------------------------------------------------------------ preparation
    def prepare(self):
        cfg = self.cfg
        MM.check_path(cfg["tasks_file"], "task file")
        self.T = {}
        for line in open(cfg["tasks_file"], encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if r["task_id"] in self.T:
                    fail(f"task file: duplicate id {r['task_id']}")
                self.T[r["task_id"]] = r
        MM.register("task file", cfg["tasks_file"], len(self.T))
        for d in cfg["gold"].get("dirs_first", []) + cfg["gold"].get("dirs_after", []):
            if not os.path.isdir(d):
                fail(f"gold folder missing: {d}")
        an = cfg["analyses"]
        self.sets = {}
        for key, scfg in cfg["sets"].items():
            if key not in SETTOK:
                fail(f"set key {key!r} has no macro token (make_macros.SETTOK: {sorted(SETTOK)})")
            label = f"set {key}"
            ids = read_ids(scfg["ids"], self.T, f"{label} ids")
            if len(ids) != scfg["expect_n"]:
                fail(f"{label}: {len(ids)} ids, the config expects {scfg['expect_n']}")
            rows = read_set_rows(scfg, ids, f"{label} per-task rows")
            excl = declared_exclusions(scfg, label)
            excl = {t: w for t, w in excl.items() if t in rows}
            if excl:
                log(f"WARNING {label}: {len(excl)} tasks excluded by the config (their scored edited model is gone): "
                    f"{sorted(excl)}")
            exp = {t: r for t, r in rows.items() if t not in excl}
            self.sets[key] = {"cfg": scfg, "ids": ids, "rows": rows, "expected": exp, "excluded": excl}
        for a in ("offtarget", "gate", "relaxed"):
            for s in an.get(a, []):
                if s not in self.sets:
                    fail(f"analyses.{a} names the set {s!r}, which the config does not define")
        for s in an.get("schema", {}):
            if s not in self.sets:
                fail(f"analyses.schema names the set {s!r}, which the config does not define")
        # what each task of each set needs
        loc = Locator(self.work_dir, self.tag or "run")
        self.plan, missing, sources_missing = {}, [], []
        for key, S in self.sets.items():
            exp = S["expected"]
            scope = set()
            sc = an.get("schema", {}).get(key)
            if sc:
                ids = sorted(exp)
                if sc.get("sample"):
                    ids = OC.schema_draw(sorted(S["rows"]), sc["sample"], sc["seed"], sc.get("take", 0))
                    S["draw"] = list(ids)
                    ids = [i for i in ids if i in exp]
                big = [i for i in ids if os.path.getsize(self.src(i)) > sc["max_src_mb"] * 1e6]
                S["schema_left_out"] = sorted(big)
                scope = set(ids) - set(big)
                S["schema_scope"] = sorted(scope)
            plan = {}
            overrides = S["cfg"].get("override_archives", [])
            for t, r in exp.items():
                need = []
                if key in an.get("offtarget", []) and OC.completed(r):
                    need.append("offtarget")
                if key in an.get("gate", []):
                    need.append("gate")
                if t in scope:
                    need.append("schema")
                if not need:
                    continue
                if not os.path.isfile(self.src(t)):
                    sources_missing.append((key, t, str(self.src(t))))
                where = loc.resolve(r, overrides)
                if where[0] == "missing":
                    missing.append((key, t, where[1]))
                plan[t] = {"need": need, "where": where}
            self.plan[key] = plan
        self.loc = loc
        if sources_missing:
            fail(f"{len(sources_missing)} source models missing, for example {sources_missing[:3]}")
        bad = missing
        if bad:
            fail(f"{len(bad)} edited models are neither on disk nor in their archive (the run is refused): "
                 + "; ".join(f"{k} {t}: {w}" for k, t, w in bad[:10]) + (" ..." if len(bad) > 10 else ""))
        self.missing = missing
        # gold archives exist (the checksum is checked when each one is unpacked)
        import vworker as VW
        nog = [t for S in self.sets.values() for t in S["expected"]
               if not any(p.is_file() for p in VW.gold_candidates(self.T[t], self.cfg["gold"]))]
        if nog:
            fail(f"{len(nog)} tasks have no ground-truth archive, for example {nog[:3]}")
        for arc, mem in loc.lists.items():
            if mem is not None:
                MM.register(f"edited-model archive ({len(mem)} members)", arc, len(mem))

    def src(self, t):
        return Path(".") / self.T[t]["input_ifc"]

    # ------------------------------------------------------------ raw rows (resume)
    def raw_path(self, key, a):
        return self.work_dir / f"raw_{self.tag}_{key}_{a}.jsonl"

    @staticmethod
    def row_ok(a, r):
        if a == "offtarget":
            return r.get("status") == "ok"
        return not r.get("error")

    def load_raw(self, key, a):
        p = self.raw_path(key, a)
        out = {}
        if p.is_file():
            for line in open(p, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    out[r["task_id"]] = r
        return out

    # ------------------------------------------------------------ pool
    def pool(self):
        if self.ex is None:
            ctx = mp.get_context("spawn")
            self.ex = cf.ProcessPoolExecutor(max_workers=self.workers, mp_context=ctx, initializer=_child_init,
                                             initargs=(self.cfg_path, str(HERE)), max_tasks_per_child=20)
        return self.ex

    def kill_pool(self):
        if self.ex is None:
            return
        procs = list(getattr(self.ex, "_processes", {}).values())
        self.ex.shutdown(wait=False, cancel_futures=True)
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        self.ex = None

    # ------------------------------------------------------------ one set
    def run_set(self, key):
        S, plan = self.sets[key], self.plan[key]
        raw = {a: self.load_raw(key, a) for a in ANALYSES}
        sinks = {a: open(self.raw_path(key, a), "a", encoding="utf-8") for a in ANALYSES}
        reuse = self.lim.get("reuse_rows_across_sets", True)
        todo = {}
        reused = 0
        for t, p in plan.items():
            need = [a for a in p["need"] if not (t in raw[a] and self.row_ok(a, raw[a][t]))]
            if reuse and need:
                for a in list(need):
                    hit = self.find_reuse(key, a, t, p["where"])
                    if hit is not None:
                        if a == "offtarget":
                            hit = dict(hit, arm=key)
                        sinks[a].write(json.dumps(hit, default=str) + "\n")
                        raw[a][t] = hit
                        need.remove(a)
                        reused += 1
            if need:
                todo[t] = need
        for f in sinks.values():
            f.flush()
        log(f"set {key}: {len(plan)} tasks with an analysis, {len(plan) - len(todo)} complete from earlier rows "
            f"({reused} analyses reused from another set), {len(todo)} to run")
        if not todo:
            for f in sinks.values():
                f.close()
            return
        items = []
        for t, need in todo.items():
            items.append({"record": self.T[t], "row": S["expected"][t], "which": need, "set": key, "where": plan[t]["where"]})
        direct = [it for it in items if it["where"][0] in ("disk", "none", "missing")]
        by_arc = {}
        for it in items:
            if it["where"][0] == "tar":
                by_arc.setdefault(it["where"][1], {})[it["where"][2]] = it
        self.inflight = {}           # future -> (item, local path or None, size, tries)
        self.last_done = time.time()
        self.n_done, self.n_total, self.t_start = 0, len(items), time.time()

        def on_result(it, res):
            for a in it["which"]:
                r = res.get(a)
                if r is None:
                    r = {"task_id": it["record"]["task_id"], "error": "worker returned no row"}
                    if a == "offtarget":
                        r = {"arm": key, "task_id": it["record"]["task_id"], "status": "error", "error": r["error"]}
                r["edited_source"] = "::".join(str(x) for x in it["where"][1:3]) if it["where"][0] == "tar" else \
                    f"{it['where'][0]}:{it['where'][1]}"
                sinks[a].write(json.dumps(r, default=str) + "\n")
                sinks[a].flush()
                raw[a][r["task_id"]] = r

        for it in direct:
            if it["where"][0] == "missing":
                res = {}
                for a in it["which"]:
                    res[a] = ({"arm": key, "task_id": it["record"]["task_id"], "status": "edited_missing",
                               "error": it["where"][1], "seconds": 0.0} if a == "offtarget" else
                              {"task_id": it["record"]["task_id"], "error": f"edited model missing: {it['where'][1]}"})
                on_result(it, res)
                continue
            path = it["where"][1] if it["where"][0] == "disk" else None
            self.submit(it, path, None, 0, on_result)
        for arc, wanted in sorted(by_arc.items()):
            log(f"set {key}: {len(wanted)} edited models from {arc}")
            seen = set()
            with tarfile.open(arc, "r|gz") as tf:
                for m in tf:
                    if not m.isfile():
                        continue
                    name = _norm_member(m.name)
                    if name not in wanted:
                        continue
                    it = wanted[name]
                    self.make_room(m.size, on_result)
                    dest = self.scratch / "edited" / key / it["record"]["task_id"]
                    dest.mkdir(parents=True, exist_ok=True)
                    target = dest / Path(name).name
                    with tf.extractfile(m) as s, open(target, "wb") as d:
                        shutil.copyfileobj(s, d, 1 << 20)
                    self.unpacked += m.size
                    self.stats["peak_unpacked_gb"] = max(self.stats["peak_unpacked_gb"], self.unpacked / 1e9)
                    seen.add(name)
                    self.submit(it, str(target), m.size, 0, on_result)
                    if len(seen) == len(wanted):
                        break
            for name, it in wanted.items():
                if name not in seen:
                    on_result(it, {a: ({"arm": key, "task_id": it["record"]["task_id"], "status": "edited_missing",
                                        "error": f"{name} not met while streaming {arc}"} if a == "offtarget" else
                                       {"task_id": it["record"]["task_id"], "error": f"{name} not met while streaming {arc}"})
                                   for a in it["which"]})
        while self.inflight:
            self.collect(on_result, block=True)
        for f in sinks.values():
            f.close()

    def find_reuse(self, key, a, t, where):
        """A row of the same analysis, task, edited model and per-task row in a set already run (e.g. the 108-task
        slice of the benchmark read): the analysis would read the same three files and give the same row."""
        row = self.sets[key]["expected"][t]
        for k2 in self.cfg["sets"]:
            if k2 == key or k2 not in getattr(self, "done_sets", set()):
                continue
            p2 = self.plan.get(k2, {}).get(t)
            if not p2 or p2["where"] != where:
                continue
            r2 = self.sets[k2]["expected"].get(t)
            if r2 is None or r2.get("score") != row.get("score") or r2.get("edited_ifc") != row.get("edited_ifc"):
                continue
            prev = self.load_raw_cached(k2, a).get(t)
            if prev is not None and self.row_ok(a, prev):
                return prev
        return None

    def load_raw_cached(self, k2, a):
        c = self.__dict__.setdefault("_rawcache", {})
        if (k2, a) not in c:
            c[(k2, a)] = self.load_raw(k2, a)
        return c[(k2, a)]

    def submit(self, it, path, size, tries, on_result):
        while len(self.inflight) >= 2 * self.workers:
            self.collect(on_result, block=True)
        while mem_available_gb() < self.min_mem and self.inflight:
            self.collect(on_result, block=True, timeout=30)
        payload = {"record": it["record"], "row": it["row"], "path": path, "which": it["which"], "set": it["set"]}
        fut = self.pool().submit(_child_work, payload)
        self.inflight[fut] = (it, path, size, tries)

    def make_room(self, size, on_result):
        if size > self.max_unpacked:
            fail(f"one edited model is {size / 1e9:.1f} GB, above limits.max_unpacked_gb")
        while True:
            free = free_gb(self.scratch)
            if self.unpacked + size <= self.max_unpacked and free - size / 1e9 >= self.min_free:
                return
            if not self.inflight:
                raise GenError(f"disk: {free:.1f} GB free; unpacking {size / 1e6:.0f} MB would leave less than "
                               f"{self.min_free} GB (nothing of this run is unpacked; another process uses the disk)")
            self.collect(on_result, block=True)

    def release(self, path, size):
        if path and size is not None:
            p = Path(path)
            if p.is_relative_to(self.scratch):
                shutil.rmtree(p.parent, ignore_errors=False)
                self.unpacked -= size

    def collect(self, on_result, block=True, timeout=60):
        if not self.inflight:
            return
        done, _ = cf.wait(list(self.inflight), timeout=timeout if block else 0, return_when=cf.FIRST_COMPLETED)
        if not done:
            if time.time() - self.last_done > self.stall_s:
                names = [v[0]["record"]["task_id"] for v in self.inflight.values()]
                self.kill_pool()
                raise GenError(f"no analysis returned for {self.stall_s / 60:.0f} minutes; in flight: {names}")
            return
        broken = []
        for fut in done:
            it, path, size, tries = self.inflight.pop(fut)
            try:
                res = fut.result()
            except BrokenProcessPool:
                broken.append((it, path, size, tries))
                continue
            except Exception as exc:  # noqa: BLE001  an exception outside the old functions' own try blocks
                res = {a: ({"arm": it["set"], "task_id": it["record"]["task_id"], "status": "error",
                            "error": f"{type(exc).__name__}: {exc}"[:400]} if a == "offtarget" else
                           {"task_id": it["record"]["task_id"], "error": f"{type(exc).__name__}: {exc}"[:400]})
                       for a in it["which"]}
            on_result(it, res)
            if isinstance(res, dict) and res.get("worker_maxrss_mb"):
                self.stats["peak_worker_rss_mb"] = max(self.stats["peak_worker_rss_mb"], float(res["worker_maxrss_mb"]))
            if self.n_done % 5 == 0:
                self.stats["peak_scratch_gb"] = max(self.stats["peak_scratch_gb"], tree_gb(self.scratch))
            self.release(path, size)
            self.last_done = time.time()
            self.n_done += 1
            if self.n_done % 25 == 0 or self.n_done == self.n_total:
                el = time.time() - self.t_start
                log(f"set {it['set']}: {self.n_done}/{self.n_total} done, {el / 60:.1f} min, unpacked "
                    f"{self.unpacked / 1e9:.2f} GB, scratch {tree_gb(self.scratch):.2f} GB, free {free_gb(self.scratch):.1f} GB, "
                    f"memory available {mem_available_gb():.1f} GB")
        if broken:
            # a worker died: every future of the pool fails; resubmit them once, then record the failure
            more = [v for v in self.inflight.values()]
            self.inflight.clear()
            self.kill_pool()
            log(f"WARNING a worker process died; {len(broken) + len(more)} analyses are resubmitted once")
            for it, path, size, tries in broken + more:
                if tries >= 1:
                    on_result(it, {a: ({"arm": it["set"], "task_id": it["record"]["task_id"], "status": "error",
                                        "error": "worker process died twice on this task"} if a == "offtarget" else
                                       {"task_id": it["record"]["task_id"], "error": "worker process died twice on this task"})
                                   for a in it["which"]})
                    self.release(path, size)
                else:
                    self.submit(it, path, size, tries + 1, on_result)

    def run(self):
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.done_sets = set()
        try:
            for key in self.cfg["sets"]:
                if self.plan.get(key):
                    t0 = time.time()
                    self.run_set(key)
                    self.stats["sets"][key] = {"wall_minutes": round((time.time() - t0) / 60, 1),
                                               "analyses_run": getattr(self, "n_total", 0)}
                self.done_sets.add(key)
        finally:
            self.kill_pool()
            ed = self.scratch / "edited"
            if ed.exists():
                shutil.rmtree(ed)
            self.unpacked = 0


def _child_init(cfg_path, here):
    sys.path.insert(0, here)
    import vworker
    vworker.init(cfg_path)


def _child_work(payload):
    import vworker
    return vworker.work(payload)


# ====================================================================== summaries, macros, fragments
def mm(x):
    return f"{1000 * x:.1f}"


def summarize(R):
    cfg, an = R.cfg, R.cfg["analyses"]
    data = {"sets": {}, "failures": [], "excluded": {}}
    gold_files, gold_skipped = {}, {}
    for key, S in R.sets.items():
        D = data["sets"][key] = {"n_ids": len(S["ids"]), "n_expected": len(S["expected"]),
                                 "excluded": S["excluded"],
                                 "completed": sum(1 for r in S["expected"].values() if OC.completed(r))}
        if S["excluded"]:
            data["excluded"][key] = S["excluded"]
        plan = R.plan.get(key, {})
        raw = {a: R.load_raw(key, a) for a in ANALYSES}
        for a in ANALYSES:
            want = [t for t, p in plan.items() if a in p["need"]]
            have = {t: raw[a][t] for t in want if t in raw[a]}
            bad = sorted(t for t in want if t not in have or not R.row_ok(a, have[t]))
            for t in bad:
                r = have.get(t, {})
                data["failures"].append({"set": key, "analysis": a, "task_id": t,
                                         "error": r.get("error") or r.get("status") or "no row"})
            raw[a] = have
            for t, r in have.items():
                if r.get("gold_file"):
                    gold_files.setdefault(t, set()).add(r["gold_file"])
                    if r.get("gold_skipped"):
                        gold_skipped[t] = r["gold_skipped"]
        exp = S["expected"]
        run_label = f"{cfg['model']} ({key})"
        if key in an.get("offtarget", []):
            OT = _ot_module()
            rows = list(raw["offtarget"].values())
            n_comp = sum(1 for r in exp.values() if OC.completed(r))
            D["offtarget"] = OT._arm_summary(rows, n_comp)
            D["offtarget"]["per_task"] = [{"task_id": r["task_id"], "status": r.get("status"), "n_any": r.get("n_any"),
                                           **{f"n_{c}": r.get(f"n_{c}") for c in OT.CLASSES}} for r in rows]
        if key in an.get("gate", []):
            g = raw["gate"]
            gs, lost = OC.gate_summary(key, run_label, exp, g)
            recs = OC.abs_records(key, g)
            D["gate"] = gs
            D["gate_lost"] = lost
            D["gate_per_task"] = [{"task_id": t, "completed": r.get("completed"), "gate_pass": r.get("gate_pass"),
                                   "gate_strict_pass": r.get("gate_strict_pass"), "gate": r.get("gate"),
                                   "gate_reasons": r.get("gate_reasons")} for t, r in sorted(g.items())]
            D["abs"] = OC.abs_summary(recs)
            D["abs_within_1cm_share"] = OC.within_cm_share(recs)
            D["abs_tolerance"] = OC.abs_tolerance(g)
            D["abs_targets"] = recs
            ga, ga_lost, ga_lost_cm = OC.gate_all_summary(key, exp, g)
            D["gate_all"] = ga
            D["gate_all_lost"] = ga_lost
            D["gate_all_lost_1cm"] = ga_lost_cm
            D["gt_dangling_tasks"] = sorted(t for t, r in g.items() if (r.get("dangling") or {}).get("new_dangling_gt"))
        sc = an.get("schema", {}).get(key)
        if sc:
            rows = [raw["schema"][t] for t in S["schema_scope"] if t in raw["schema"]]
            blk, srows, crows = OC.schema_summary(rows)
            D["schema"] = blk
            D["schema_rows"] = srows
            D["clash_rows"] = crows
            D["schema_scope"] = {"max_src_mb": sc["max_src_mb"], "n_in_scope": len(S["schema_scope"]),
                                 "left_out_large_source": S["schema_left_out"], "draw": S.get("draw"),
                                 "sample": sc.get("sample"), "take": sc.get("take"), "seed": sc.get("seed"),
                                 "excluded_from_draw": sorted(set(S.get("draw") or []) - set(exp))}
        if key in an.get("relaxed", []):
            D["relaxed"] = OC.relaxed_rule(exp, R.T, sorted(exp))
    # totals over the stored arms, the proposed model's 108-task row replaced
    oa = cfg.get("other_arms")
    if oa and "sub108" in data["sets"] and "gate" in data["sets"]["sub108"]:
        g108 = data["sets"]["sub108"]
        for k in ("gate_summary", "gate_lost_csv", "gate_ext_summary", "gate_ext_lost_csv"):
            MM.check_path(oa[k], f"other_arms.{k}")
        GS = json.load(open(oa["gate_summary"]))
        MM.register("stored gate summary (other arms)", oa["gate_summary"], len(GS))
        LT = list(csv.DictReader(open(oa["gate_lost_csv"])))
        MM.register("stored lost-completion rows (other arms)", oa["gate_lost_csv"], len(LT))
        data["gate_nine"] = OC.gate_nine_arm_totals(GS, LT, oa["replace"], g108["gate"], g108["gate_lost"], oa["arms108"])
        GX = json.load(open(oa["gate_ext_summary"]))
        MM.register("stored 27-arm gate summary", oa["gate_ext_summary"], len(GX["table_rows"]))
        LX = list(csv.DictReader(open(oa["gate_ext_lost_csv"])))
        MM.register("stored 27-arm lost-completion rows", oa["gate_ext_lost_csv"], len(LX))
        gs = g108["gate"]
        data["gate_ext"] = OC.gate_ext_totals(GX["table_rows"], LX, oa["replace"], gs["completed_paper_rule"],
                                              gs["completed_gated"], gs["lost"], g108["gate_lost"],
                                              set(oa["local_arms"]))
    two = {t: sorted(v) for t, v in gold_files.items() if len(v) > 1}
    if two:
        data["failures"].append({"set": "*", "analysis": "ground truth", "task_id": sorted(two)[0],
                                 "error": f"{len(two)} tasks were compared with different ground-truth files: {two}"})
    data["ground_truth"] = {"files": {t: sorted(v)[0] for t, v in sorted(gold_files.items())},
                            "first_candidate_skipped": gold_skipped,
                            "note": "the ground truth used is the first candidate of the config's gold order whose "
                                    "SHA-256 equals the task record's verification.gold_sha256; "
                                    "first_candidate_skipped lists the tasks where an earlier existing file did not match"}
    import ifcopenshell
    data["validator"] = {"ifcopenshell": ifcopenshell.version}
    return data


_OT = {}


def _ot_module():
    if "m" not in _OT:
        sys.path.insert(0, "checker")
        import offtarget_full_v4e as OT    # noqa: E402  (no file is written at import)
        _OT["m"] = OT
    return _OT["m"]


def write_macros(R, data):
    o = MM.Out()
    cfg, an = R.cfg, R.cfg["analyses"]
    thou = MM.thou
    src0 = f"run_validity.py ({cfg['label']})"

    def S(key):
        return SETTOK[key]

    o.section(1, "off-target changes of completed outputs (offtarget_full_v4e.evaluate, _arm_summary)")
    for key in an.get("offtarget", []):
        a = data["sets"][key]["offtarget"]
        st = f"Pm{S(key)}Off"
        src = f"{src0}: sets.{key}.offtarget"
        o.put(st + "Done", thou(a["n_completed"]), a["n_completed"], src + ".n_completed (completed outputs)")
        o.put(st + "Evaluated", thou(a["n_evaluated"]), a["n_evaluated"], src + ".n_evaluated (diffed, status ok)")
        o.put(st + "Any", thou(a["n_with_any"]), a["n_with_any"], src + ".n_with_any (at least one off-target change)")
        for c, tok in (("geometry", "Geometry"), ("relation", "Relation"), ("property", "Property"),
                       ("attribute", "Attribute"), ("other_objects", "OtherObjects")):
            o.put(st + tok, thou(a["by_class"][c]["n_files"]), a["by_class"][c]["n_files"], src + f".by_class.{c}.n_files")
        med = a["median_count_per_affected_file"]
        o.put(st + "Median", "--" if med is None else f"{med}", med, src + ".median_count_per_affected_file")
    o.section(2, "absolute errors of the edit targets and the 1 cm tolerance (gate_abs.abs_errors, abs_tolerance.py)")
    for key in an.get("gate", []):
        D = data["sets"][key]
        c, t = D["abs"]["completed"], D["abs_tolerance"]
        st = f"Pm{S(key)}Abs"
        src = f"{src0}: sets.{key}.abs.completed"
        o.put(st + "Targets", thou(c["n_targets"]), c["n_targets"], src + ".n_targets (targets of completed edits)")
        o.put(st + "Tasks", thou(c["n_tasks"]), c["n_tasks"], src + ".n_tasks")
        if c["n_targets"]:
            p, dm = c["position"], c["dimension_max"]
            for q, qt in (("median", "Median"), ("p95", "NinetyFive"), ("p99", "NinetyNine"), ("max", "Max")):
                o.put(st + "Pos" + qt, mm(p[q]), p[q], src + f".position.{q} x 1000 (centre error, mm)")
            o.put(st + "DimMax", mm(dm["max"]), dm["max"], src + ".dimension_max.max x 1000 (largest dimension error, mm)")
            w = D["abs_within_1cm_share"]
            o.put(st + "WithinCmPct", f"{100 * w:.1f}", w, f"{src0}: completed targets with centre and largest "
                  "dimension error both <= 1 cm, percent")
        else:
            o.skip(f"{st}Pos..., DimMax, WithinCmPct", "no target of a completed edit")
        o.put(st + "Done", thou(t["completed"]), t["completed"], f"{src0}: sets.{key}.abs_tolerance.completed")
        for cm_, tok in ((1, "Cm"), (2, "TwoCm"), (5, "FiveCm"), (10, "TenCm")):
            o.put(st + "Done" + tok, thou(t[f"completed_within_{cm_}cm"]), t[f"completed_within_{cm_}cm"],
                  f"{src0}: sets.{key}.abs_tolerance.completed_within_{cm_}cm")
        lostcm = t["completed"] - t["completed_within_1cm"]
        o.put(st + "CmLost", thou(lostcm), lostcm, f"{src0}: completions a 1 cm tolerance would remove "
              f"(abs_tolerance.lost_at_1cm: {t['lost_at_1cm']})")
    o.section(3, "new schema errors and hard clashes (schema_clash.process, summarize_schema_clash)")
    scfg = an.get("schema", {})
    if scfg:
        lim = {v["max_src_mb"] for v in scfg.values()}
        if len(lim) != 1:
            fail("analyses.schema: every set must use the same source-size limit (one macro prints it)")
        lim = lim.pop()
        o.put("PmSchemaSizeLimitMB", f"{lim:g}", lim, f"{src0}: analyses.schema.*.max_src_mb (source-size limit, MB)")
        o.put("PmSchemaValidatorVersion", data["validator"]["ifcopenshell"], data["validator"]["ifcopenshell"],
              f"{src0}: ifcopenshell.version of the environment that validated")
    for key, sc in scfg.items():
        D = data["sets"][key]
        tok = S(key) + ("Sample" if sc.get("sample") else "")
        st = f"Pm{tok}"
        src = f"{src0}: sets.{key}.schema"
        sp = D["schema_scope"]
        if sc.get("sample"):
            o.put(st + "DrawPool", thou(sc["sample"]), sc["sample"], f"{src0}: analyses.schema.{key}.sample "
                  "(random.Random(seed).sample(sorted ids, sample), schema_clash.main)")
            o.put(st + "DrawN", thou(sc["take"]), sc["take"], f"{src0}: analyses.schema.{key}.take (the first draws)")
            o.put(st + "DrawSeed", f"{sc['seed']}", sc["seed"], f"{src0}: analyses.schema.{key}.seed")
        o.put(st + "SchemaScopeN", thou(sp["n_in_scope"]), sp["n_in_scope"], src + "_scope.n_in_scope (tasks validated)")
        o.put(st + "SchemaLeftOut", thou(len(sp["left_out_large_source"])), len(sp["left_out_large_source"]),
              src + "_scope.left_out_large_source (source above the size limit)")
        c = D["schema"]["completed"]
        for k_, tk in (("n", "SchemaN"), ("tasks_with_new_errors_gt", "SchemaGtTasks"),
                       ("new_errors_gt_total", "SchemaGtErrors"), ("tasks_with_new_errors_output", "SchemaOutTasks"),
                       ("new_errors_output_total", "SchemaOutErrors"),
                       ("tasks_output_errors_beyond_gt", "SchemaBeyondTasks"),
                       ("output_errors_beyond_gt_total", "SchemaBeyondErrors"),
                       ("n_with_clash_check", "ClashN"), ("tasks_with_new_clash_gt", "ClashGtTasks"),
                       ("new_clashes_gt_total", "ClashGtClashes"), ("tasks_with_new_clash_output", "ClashOutTasks"),
                       ("new_clashes_output_total", "ClashOutClashes"),
                       ("tasks_output_clash_beyond_gt", "ClashBeyondTasks"),
                       ("output_clashes_beyond_gt_total", "ClashBeyondClashes")):
            o.put(st + tk, thou(c[k_]), c[k_], src + f".completed.{k_}")
        a_ = D["schema"]["all"]
        o.put(st + "ClashAllBeyondTasks", thou(a_["tasks_output_clash_beyond_gt"]), a_["tasks_output_clash_beyond_gt"],
              src + ".all.tasks_output_clash_beyond_gt (all edits, completed or not)")
        o.put(st + "SchemaAllBeyondTasks", thou(a_["tasks_output_errors_beyond_gt"]), a_["tasks_output_errors_beyond_gt"],
              src + ".all.tasks_output_errors_beyond_gt (all edits, completed or not)")
    o.section(4, "completion under the relation gate, its strict variant, 1 cm, and the relaxed reading")
    for key in an.get("gate", []):
        D = data["sets"][key]
        g, ga = D["gate"], D["gate_all"]
        st = f"Pm{S(key)}Gate"
        src = f"{src0}: sets.{key}.gate"
        o.put(st + "Before", thou(g["completed_paper_rule"]), g["completed_paper_rule"], src + ".completed_paper_rule")
        o.put(st + "After", thou(g["completed_gated"]), g["completed_gated"], src + ".completed_gated (relation checks added)")
        o.put(st + "AfterStrict", thou(g["completed_gated_strict"]), g["completed_gated_strict"], src + ".completed_gated_strict")
        o.put(st + "Lost", thou(g["lost"]), g["lost"], src + ".lost")
        o.put(st + "LostStrict", thou(g["lost_strict"]), g["lost_strict"], src + ".lost_strict")
        n = g["n_tasks"]
        o.put(st + "AfterComp", MM.num(g["completed_gated"] / n), g["completed_gated"] / n,
              src + ".completed_gated / n_tasks (gated completion)")
        o.put(st + "Both", thou(ga["completed_gated_and_1cm"]), ga["completed_gated_and_1cm"],
              f"{src0}: sets.{key}.gate_all.completed_gated_and_1cm (gate and 1 cm together)")
        o.put(st + "BothComp", MM.num(ga["completed_gated_and_1cm"] / n), ga["completed_gated_and_1cm"] / n,
              f"{src0}: sets.{key}.gate_all.completed_gated_and_1cm / n_tasks")
        o.put(st + "GtDanglingTasks", thou(len(D["gt_dangling_tasks"])), len(D["gt_dangling_tasks"]),
              src + "_per_task: tasks whose ground truth leaves a relationship with an empty required end")
    for key in an.get("relaxed", []):
        rx = data["sets"][key]["relaxed"]
        st = f"Pm{S(key)}Relax"
        src = f"{src0}: sets.{key}.relaxed"
        o.put(st + "Under", thou(rx["n_underspecified"]), rx["n_underspecified"], src + ".n_underspecified")
        o.put(st + "Published", thou(rx["completed_published_rule"]), rx["completed_published_rule"],
              src + ".completed_published_rule")
        o.put(st + "Done", thou(rx["completed_without_question_mark_rule"]), rx["completed_without_question_mark_rule"],
              src + ".completed_without_question_mark_rule (t4b_relaxed_rule)")
    if "gate_nine" in data:
        o.section(5, "totals over the stored 108-task arms, the proposed model's row replaced")
        nine, ext = data["gate_nine"], data["gate_ext"]
        src = f"{src0}: gate_nine (gate_summary.json and lost_tasks_gated.csv of the other arms)"
        o.put("PmGateArms", thou(nine["arms"]), nine["arms"], src + ", arms")
        o.put("PmGateLostTotal", thou(nine["lost_total"]), nine["lost_total"], src + ", completions lost summed over the arms")
        o.put("PmGateLostArms", thou(nine["lost_arms"]), nine["lost_arms"], src + f", arms with a loss: {nine['lost_arm_keys']}")
        o.put("PmGateLostTasks", thou(nine["lost_tasks"]), nine["lost_tasks"], src + ", lost rows")
        o.put("PmGateLostDeletions", thou(nine["lost_deletions"]), nine["lost_deletions"], src + ", lost rows with operation delete")
        src = f"{src0}: gate_ext (gate_summary_ext.json and lost_tasks_gated_ext.csv of the other arms)"
        o.put("PmGateExtArms", thou(ext["arms"]), ext["arms"], src + ", arms of the main results table")
        o.put("PmGateExtLostTotal", thou(ext["lost_total"]), ext["lost_total"], src + ", completions removed over all arms")
        o.put("PmGateExtLostDeletions", thou(ext["lost_deletions"]), ext["lost_deletions"], src + ", of them deletions")
        o.put("PmGateExtLostDeletionsCommercial", thou(ext["lost_deletions_commercial"]), ext["lost_deletions_commercial"],
              src + ", deletions by commercial models (arms not in other_arms.local_arms)")
        o.put("PmGateExtLostOther", thou(ext["lost_other"]), ext["lost_other"], src + ", removals that are not deletions")
        o.put("PmGateExtLostArms", thou(ext["lost_arms"]), ext["lost_arms"], src + ", arms that lose at least one completion")
        o.put("PmGateExtMaxLost", thou(ext["max_lost"]), ext["max_lost"], src + f", largest loss in one arm ({ext['max_lost_arms']})")
    return o


def write_fragments(R, data, prefix):
    cfg, an = R.cfg, R.cfg["analyses"]
    labs = cfg.get("table_labels", {})
    thou = MM.thou
    frags = {}
    hdr = f"% GENERATED by analysis/validity/run_validity.py ({cfg['label']}); rows of the proposed model only."

    def lab(table, key):
        v = labs.get(table, {}).get(key)
        if v is None:
            fail(f"table_labels.{table}.{key} missing in the config")
        return v
    if an.get("schema"):
        L = []
        for key, sc in an["schema"].items():
            c = data["sets"][key]["schema"]["completed"]

            def tc(a, b):
                return f"{a} ({b})"
            L.append(f"{lab('tab_schema', key)} & {c['n']} & {tc(c['tasks_with_new_errors_gt'], c['new_errors_gt_total'])} & "
                     f"{tc(c['tasks_with_new_errors_output'], c['new_errors_output_total'])} & "
                     f"{tc(c['tasks_output_errors_beyond_gt'], c['output_errors_beyond_gt_total'])} & {c['n_with_clash_check']} & "
                     f"{tc(c['tasks_with_new_clash_gt'], c['new_clashes_gt_total'])} & "
                     f"{tc(c['tasks_with_new_clash_output'], c['new_clashes_output_total'])} & "
                     f"{tc(c['tasks_output_clash_beyond_gt'], c['output_clashes_beyond_gt_total'])} \\\\")
        frags["tab_schema"] = L
    if an.get("gate"):
        L, G = [], []
        for key in an["gate"]:
            D = data["sets"][key]
            c, t = D["abs"]["completed"], D["abs_tolerance"]
            if key in labs.get("tab_abserr", {}):
                p, dm = c["position"], c["dimension_max"]
                L.append(f"{lab('tab_abserr', key)} & {thou(c['n_targets'])} & {mm(p['median'])} & {mm(p['p95'])} & "
                         f"{mm(p['p99'])} & {mm(p['max'])} & {mm(dm['max'])} & {100 * D['abs_within_1cm_share']:.1f} & "
                         f"{thou(t['completed'])} & {thou(t['completed_within_1cm'])} \\\\")
            if key in labs.get("tab_gate_all", {}):
                s = D["gate_all"]
                m_, a_ = lab("tab_gate_all", key)
                N = s["n_tasks"]
                G.append(f"{m_} & {a_} & {N:,} & {OC.gate_all_cell(s['completed'], N)} & "
                         f"{OC.gate_all_cell(s['completed_gated'], N)} & {OC.gate_all_cell(s['completed_1cm'], N)} & "
                         f"{OC.gate_all_cell(s['completed_gated_and_1cm'], N)} \\\\")
        if L:
            frags["tab_abserr"] = L
        if G:
            frags["tab_gate_all"] = G
    if an.get("offtarget"):
        L = []
        for key in an["offtarget"]:
            a = data["sets"][key]["offtarget"]
            bc, med = a["by_class"], a["median_count_per_affected_file"]
            L.append(f"{lab('tab_offtarget', key)} & {thou(a['n_evaluated'])} & {a['n_with_any']} & "
                     f"{bc['geometry']['n_files']} & {bc['relation']['n_files']} & {bc['property']['n_files']} & "
                     f"{bc['attribute']['n_files']} & {'--' if med is None else med} \\\\")
        frags["tab_offtarget"] = L
    written = {}
    for name, rows in frags.items():
        p = f"{prefix}frag_{name}.tex"
        MM.guard_output(p)
        open(p, "w", encoding="utf-8").write("\n".join([hdr] + rows) + "\n")
        written[name] = {"path": p, "rows": rows}
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", required=True)
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args()
    try:
        cfg = load_config(args.config)
        R = Runner(cfg, args.config)
        Path(cfg["out"]["work_dir"]).mkdir(parents=True, exist_ok=True)
        R.prepare()
        if cfg.get("avoid_names_from"):
            MM.check_path(cfg["avoid_names_from"], "avoid_names_from")
            R.avoid = set(json.load(open(cfg["avoid_names_from"]))["macros"])
        else:
            R.avoid = set()
        free = free_gb(cfg["out"]["scratch"] if os.path.isdir(cfg["out"]["scratch"]) else cfg["out"]["work_dir"])
        if free < R.min_free:
            fail(f"disk: {free:.1f} GB free, below limits.min_free_gb = {R.min_free}")
        counts = {k: {"tasks": len(p), "disk": sum(1 for v in p.values() if v["where"][0] == "disk"),
                      "archive": sum(1 for v in p.values() if v["where"][0] == "tar"),
                      "none": sum(1 for v in p.values() if v["where"][0] == "none"),
                      "unpacked GB if all": round(sum(v["where"][3] for v in p.values() if v["where"][0] == "tar") / 1e9, 2),
                      **{a: sum(1 for v in p.values() if a in v["need"]) for a in ANALYSES}}
                  for k, p in R.plan.items()}
        log(f"preflight passed: {json.dumps(counts)}; {free:.1f} GB free")
        if args.preflight_only:
            return
        R.run()
        data = summarize(R)
        J = {"generator": "analysis/validity/run_validity.py", "config": os.path.abspath(args.config),
             "label": cfg["label"], "model": cfg["model"],
             "inputs": [{"label": a, "path": p, "rows": n, "sha256": h} for a, p, n, h in MM.INPUTS],
             "data": MM.jsonable(data), "run_stats": R.stats}
        MM.guard_output(cfg["out"]["json"])
        if data["failures"]:
            J["status"] = f"FAILED: {len(data['failures'])} analysis rows failed; no macro file written"
            json.dump(J, open(cfg["out"]["json"], "w", encoding="utf-8"), indent=1, default=str)
            print(f"run_validity: ERROR: {len(data['failures'])} analysis rows failed, for example "
                  f"{data['failures'][:5]}; listed in {cfg['out']['json']}", file=sys.stderr)
            sys.exit(3)
        o = write_macros(R, data)
        clash = sorted(set(o.vals) & R.avoid)
        if clash:
            fail(f"{len(clash)} macro names already written by make_macros.py: {clash[:5]}")
        frags = write_fragments(R, data, cfg["out"]["fragments_prefix"])
        MM.guard_output(cfg["out"]["tex"])
    except GenError as e:
        print(f"run_validity: ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    H = [f"% GENERATED by analysis/validity/run_validity.py; do not edit by hand.",
         f"% config: {os.path.abspath(args.config)} ({cfg['label']})",
         f"% model: {cfg['model']}; completion: geometry, semantics and topology all >= 0.9",
         f"% {len(o.vals)} macros; inputs (label | rows | SHA-256 | path):"]
    for lab_, p, n, h in MM.INPUTS:
        H.append(f"%   {lab_} | {n} | {h} | {p}")
    for key, ex in data["excluded"].items():
        H.append(f"% EXCLUDED from set {key} by the config ({len(ex)} tasks, their scored edited model is gone): "
                 + ", ".join(sorted(ex)))
    gsk = data["ground_truth"]["first_candidate_skipped"]
    H.append(f"% ground truth: first file of the config's gold order whose SHA-256 equals the task record; "
             f"{len(data['ground_truth']['files'])} tasks, {len(gsk)} of them with an earlier file skipped"
             + (f" ({', '.join(sorted(gsk)[:10])}{' ...' if len(gsk) > 10 else ''})" if gsk else ""))
    if o.skipped:
        H.append(f"% not computed ({len(o.skipped)}): " + "; ".join(f"block {s['block']} {s['what']}" for s in o.skipped))
    open(cfg["out"]["tex"], "w", encoding="utf-8").write("\n".join(H + o.lines) + "\n")
    J.update(status="done", skipped=o.skipped, macros=o.vals, fragments=frags)
    json.dump(J, open(cfg["out"]["json"], "w", encoding="utf-8"), indent=1, default=str)
    log(f"run_validity: {len(o.vals)} macros, {len(frags)} fragments, {len(MM.INPUTS)} inputs")
    if cfg["limits"].get("remove_scratch_at_end", True):
        sp = Path(cfg["out"]["scratch"])
        if sp.exists():
            shutil.rmtree(sp)
            log(f"removed {sp}")


if __name__ == "__main__":
    main()
