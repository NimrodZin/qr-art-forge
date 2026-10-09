"""Gates the driver checks before and after sessions: ComfyUI idle, GPU free, GPU test,
never-economize diff, UI strings, CI on the pushed head SHA (and its failed log), budget."""
from __future__ import annotations

import ast
import datetime
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from loop.sh import as_argv, gh, git, run

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.M)
UI_FILE = "app.py"
UI_STRING = re.compile(r"label=|placeholder=|gr\.Markdown\(")


def tail(text: str, n: int) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def comfy_idle(url: str, timeout: float = 3.0) -> bool:
    """Idle iff ComfyUI's running and pending queues are both empty. Unreachable = idle
    (ComfyUI not running holds no VRAM); a reachable server with an unreadable queue = busy."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/queue", timeout=timeout) as r:
            body = r.read()
    except (OSError, urllib.error.URLError):
        return True
    try:
        q = json.loads(body)
        return not (q.get("queue_running") or q.get("queue_pending"))
    except (ValueError, AttributeError):
        return False


NVIDIA_QUERY = ["--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"]


def gpu_free(cfg: dict) -> tuple[bool, str]:
    """(ok, detail) from nvidia-smi (cfg nvidia_smi_cmd): ok iff the first GPU has at least
    gpu_min_free_mb MiB free and utilization at most gpu_max_util %. nvidia-smi missing, failing
    or unparsable → (False, why)."""
    min_free, max_util = cfg.get("gpu_min_free_mb", 7000), cfg.get("gpu_max_util", 10)
    try:
        rc, out, err = run([*as_argv(cfg.get("nvidia_smi_cmd", ["nvidia-smi"])), *NVIDIA_QUERY], ".", cfg,
                           check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"nvidia-smi not runnable: {e}"
    if rc != 0:
        return False, f"nvidia-smi exit {rc}: {(err.strip() or out.strip())[:200]}"
    line = next((l for l in out.splitlines() if l.strip()), "")
    try:
        used, total, util = (float(x) for x in line.split(","))
    except ValueError:
        return False, f"nvidia-smi output unparsable: {line[:200]!r}"
    free = total - used
    detail = (f"{free:.0f} MiB free of {total:.0f} (need ≥ {min_free}), "
              f"utilization {util:.0f} % (need ≤ {max_util})")
    return free >= min_free and util <= max_util, detail


def wait_gpu_ready(cfg: dict, poll_s: float = 10.0) -> tuple[str, str]:
    """Wait up to comfy_wait_s for ComfyUI idle and gpu_free, in one loop with one deadline.
    ("", "") when ready; else ("comfy", "") or ("gpu", gpu_free's detail) for what was still busy."""
    deadline = time.monotonic() + cfg["comfy_wait_s"]
    while True:
        busy = ("comfy", "")
        if comfy_idle(cfg["comfy_url"]):
            ok, detail = gpu_free(cfg)
            busy = ("", "") if ok else ("gpu", detail)
        if not busy[0] or time.monotonic() >= deadline:
            return busy
        time.sleep(poll_s)


class ComfyBusy(RuntimeError):
    """ComfyUI stayed busy past comfy_wait_s before a GPU run: a stop, not a retry (06 §1a)."""


class GpuBusy(ComfyBusy):
    """The GPU (nvidia-smi) stayed busy past comfy_wait_s before a GPU run: a stop, not a retry."""


def _gpu_run(cfg: dict, repo, label: str, env: dict | None) -> dict:
    what, detail = wait_gpu_ready(cfg)
    if what == "comfy":
        raise ComfyBusy(f"before the {label} run")
    if what == "gpu":
        raise GpuBusy(f"before the {label} run: {detail}")
    rc, out, err = run(cfg["gpu_cmd"], repo, cfg, check=False, timeout=cfg.get("gpu_timeout_s"),
                       keep_secrets=True, extra_env=env)
    found = re.findall(r"(\d+)/(\d+) passed", out)
    n = int(found[-1][0]) if found else 0
    return {"label": label, "pass": rc == 0 and n >= cfg["gpu_min_pass"], "n": n,
            "tail": "\n".join((out + err).strip().splitlines()[-12:])}


def gpu_test(cfg: dict, repo, env: dict | None = None) -> tuple[bool, int, str, list[dict]]:
    """Real-generation test (06 §1a): gpu_cmd with the normal env, then again with `env` added if
    given (the step's gpu_env). Pass iff every run reaches gpu_min_pass. Returns (pass, survivors,
    output tail, runs); survivors and tail are the first failing run's, else the last run's; runs
    holds {label, pass, n, tail} per run. Secrets are kept: run_batch.py may archive rejects.
    Before each run ComfyUI must be idle and the GPU free (gpu_free) within comfy_wait_s, else
    ComfyBusy, or GpuBusy naming the GPU."""
    runs = [_gpu_run(cfg, repo, "default", None)]
    if env:
        runs.append(_gpu_run(cfg, repo, "with gpu_env", env))
    ok = all(r["pass"] for r in runs)
    key = next((r for r in runs if not r["pass"]), runs[-1])
    return ok, key["n"], key["tail"], runs


GATE_IMPORT = re.compile(r"^(from validator import|import validator)")
VALIDATE_TOKEN = re.compile(r"\bvalidate\b")


def gate_spans(source: str, functions) -> list[tuple[int, int]]:
    """1-based [first, last] line ranges on `source` that are the gate: each def named in
    `functions` (decorators included) and each validator import line. Raises SyntaxError if
    `source` does not parse, LookupError if none of `functions` is defined."""
    tree = ast.parse(source)
    spans = [(min([n.lineno, *(d.lineno for d in n.decorator_list)]), n.end_lineno)
             for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in functions]
    if not spans:
        raise LookupError(f"none of {list(functions)} defined")
    return spans + [(i, i) for i, l in enumerate(source.splitlines(), 1) if GATE_IMPORT.match(l)]


def touched_never_economize(cfg: dict, repo, base: str | None = None) -> list[str]:
    """Never-economize paths in `git diff <base>...HEAD`, plus "app.py (gate)" when a hunk overlaps
    a gate span on base (gate_spans: gate_functions, validator imports), a changed line mentions a
    gate_marker or the token `validate` (e.g. a module-level rebinding), or a hunk lies within gate_context lines of a marker line on base. If base's gate
    file cannot be parsed, any change to it is flagged (fail closed) and the label says why."""
    ne = cfg["never_economize"]
    base = base or cfg.get("base_branch", "main")
    names = git(repo, "diff", "--name-only", f"{base}...HEAD").split()
    hits = [n for n in names
            if any(n == p or (p.endswith("/") and n.startswith(p)) for p in ne["paths"])]
    gf, ctx = ne["gate_file"], ne.get("gate_context", 3)
    markers = ne["gate_marker"]
    markers = [markers] if isinstance(markers, str) else list(markers)
    if gf in names:
        diff = git(repo, "diff", "-U0", f"{base}...HEAD", "--", gf)
        source = git(repo, "show", f"{base}:{gf}", check=False)
        try:
            spans = gate_spans(source, ne.get("gate_functions", []))
        except (SyntaxError, ValueError, LookupError) as e:
            hits.append(f"{gf} (gate: fail closed, {base}:{gf} unreadable: {type(e).__name__}: {e})")
            return sorted(hits)
        on_base = source.splitlines()
        spans += [(i + 1 - ctx, i + 1 + ctx) for i, l in enumerate(on_base) if any(m in l for m in markers)]
        # a changed line carrying a marker or the `validate` token (a line inside a span is a hit anyway)
        changed = [l for l in diff.splitlines()
                   if l[:1] in "+-" and not l.startswith(("+++", "---"))
                   and (any(m in l for m in markers) or VALIDATE_TOKEN.search(l[1:]))]
        near = False
        for m in HUNK.finditer(diff):
            start, count = int(m[1]), int(m[2] if m[2] is not None else 1)
            lo, hi = (start, start + count - 1) if count else (start, start + 1)
            near |= any(lo <= b and hi >= a for a, b in spans)
        if changed or near:
            hits.append(f"{gf} (gate)")
    return sorted(hits)


def ui_strings(repo, base: str) -> list[str]:
    """Lines the branch adds or changes in app.py that carry UI text (06 §4: approve by seeing)."""
    diff = git(repo, "diff", "-U0", f"{base}...HEAD", "--", UI_FILE)
    return [l[1:].strip() for l in diff.splitlines()
            if l.startswith("+") and not l.startswith("+++") and UI_STRING.search(l)]


def ci_failed_log(branch: str, cfg: dict, repo, head_sha: str, n: int = 60) -> str:
    """Last n lines of `gh run view <run> --log-failed`, the run taken from `gh run list --commit
    <head_sha>` (a failed one first), so a red attempt never shows the previous push's log."""
    _, out, err = gh(cfg, repo, "run", "list", "--commit", head_sha, "--json", "databaseId,status,conclusion",
                     check=False)
    try:
        runs = [r for r in json.loads(out or "[]") if isinstance(r, dict) and "databaseId" in r]
        failed = [r for r in runs if r.get("status") == "completed"
                  and r.get("conclusion") not in ("success", "skipped")]
        run_id = (failed or runs)[0]["databaseId"]
    except (ValueError, IndexError, TypeError):
        return (f"(no CI run found for {branch} at {head_sha[:12]}: "
                f"{err.strip()[:200] or out.strip()[:200]})")
    _, out, err = gh(cfg, repo, "run", "view", str(run_id), "--log-failed", check=False)
    return tail(out + err, n) or f"(run {run_id}: no failed-step log)"


def ci_green(pr, cfg: dict, repo, head_sha: str) -> bool:
    """CI for the pushed commit `head_sha` itself, never the PR's earlier checks (issue #28): poll
    `gh run list --commit <head_sha>` until at least one run exists and all are completed. True iff
    every conclusion is success or skipped; a completed run with any other conclusion (failure,
    cancelled, …) → False at once; ci_timeout_s → False. `pr` is the PR the SHA was pushed to."""
    deadline = time.monotonic() + cfg["ci_timeout_s"]
    while True:
        _, out, _ = gh(cfg, repo, "run", "list", "--commit", head_sha, "--json", "status,conclusion",
                       check=False)
        try:
            runs = json.loads(out or "[]")
        except ValueError:
            runs = []
        runs = [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else []
        done = [r for r in runs if r.get("status") == "completed"]
        if any(r.get("conclusion") not in ("success", "skipped") for r in done):
            return False
        if runs and len(done) == len(runs):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(cfg["ci_poll_s"])


def spent_today(runs_dir) -> float:
    today = datetime.date.today().isoformat()
    total = 0.0
    for f in Path(runs_dir).glob("*/*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("date") == today:
            total += float(rec.get("cost_usd") or 0.0)
    return total


def budget_ok(cfg: dict, runs_dir) -> tuple[bool, float]:
    total = spent_today(runs_dir)
    return total < cfg["daily_cost_ceiling_usd"], total
