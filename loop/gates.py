"""Gates the driver checks before and after sessions: ComfyUI idle, GPU test, never-economize
diff, UI strings, CI (and its failed log), budget."""
from __future__ import annotations

import ast
import datetime
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from loop.sh import gh, git, run

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


def wait_comfy_idle(cfg: dict, poll_s: float = 10.0) -> bool:
    deadline = time.monotonic() + cfg["comfy_wait_s"]
    while not comfy_idle(cfg["comfy_url"]):
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)
    return True


class ComfyBusy(RuntimeError):
    """ComfyUI stayed busy past comfy_wait_s before a GPU run: a stop, not a retry (06 §1a)."""


def _gpu_run(cfg: dict, repo, label: str, env: dict | None) -> dict:
    if not wait_comfy_idle(cfg):
        raise ComfyBusy(f"before the {label} run")
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
    Before each run ComfyUI must be idle within comfy_wait_s, else ComfyBusy."""
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


def ci_failed_log(branch: str, cfg: dict, repo=".", n: int = 60) -> str:
    """Last n lines of `gh run view <latest run on branch> --log-failed`."""
    _, out, err = gh(cfg, repo, "run", "list", "--branch", branch, "--limit", "1", "--json", "databaseId",
                     check=False)
    try:
        run_id = json.loads(out or "[]")[0]["databaseId"]
    except (ValueError, IndexError, KeyError, TypeError):
        return f"(no CI run found for {branch}: {err.strip()[:200] or out.strip()[:200]})"
    _, out, err = gh(cfg, repo, "run", "view", str(run_id), "--log-failed", check=False)
    return tail(out + err, n) or f"(run {run_id}: no failed-step log)"


def ci_green(pr, cfg: dict, repo=".") -> bool:
    """Poll `gh pr checks` until nothing is pending: True iff all pass/skipping (and ≥ 1 pass)."""
    deadline = time.monotonic() + cfg["ci_timeout_s"]
    while True:
        _, out, _ = gh(cfg, repo, "pr", "checks", str(pr), "--json", "name,bucket", check=False)
        try:
            buckets = {c.get("bucket") for c in json.loads(out or "[]")}
        except ValueError:
            buckets = set()
        if buckets & {"fail", "cancel"}:
            return False
        if "pass" in buckets and buckets <= {"pass", "skipping"}:
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
