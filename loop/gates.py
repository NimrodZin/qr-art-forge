"""Gates the driver checks before and after sessions: ComfyUI idle, GPU test, never-economize
diff, UI strings, CI (and its failed log), budget."""
from __future__ import annotations

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


def gpu_test(cfg: dict, repo) -> tuple[bool, int, str]:
    """Real-generation test (06 §1a). Returns (pass, survivors, output tail)."""
    rc, out, err = run(cfg["gpu_cmd"], repo, cfg, check=False, timeout=cfg.get("gpu_timeout_s"))
    found = re.findall(r"(\d+)/(\d+) passed", out)
    n = int(found[-1][0]) if found else 0
    tail = "\n".join((out + err).strip().splitlines()[-12:])
    return rc == 0 and n >= cfg["gpu_min_pass"], n, tail


def touched_never_economize(cfg: dict, repo, base: str | None = None) -> list[str]:
    """Never-economize paths in `git diff <base>...HEAD`, plus "app.py (THE GATE)" when a changed
    line mentions the marker or a hunk lies within gate_context lines of it on base."""
    ne = cfg["never_economize"]
    base = base or cfg.get("base_branch", "main")
    names = git(repo, "diff", "--name-only", f"{base}...HEAD").split()
    hits = [n for n in names
            if any(n == p or (p.endswith("/") and n.startswith(p)) for p in ne["paths"])]
    gf, marker, ctx = ne["gate_file"], ne["gate_marker"], ne.get("gate_context", 3)
    if gf in names:
        diff = git(repo, "diff", "-U0", f"{base}...HEAD", "--", gf)
        on_base = git(repo, "show", f"{base}:{gf}", check=False).splitlines()
        gate_lines = [i + 1 for i, l in enumerate(on_base) if marker in l]
        changed = [l for l in diff.splitlines()
                   if l[:1] in "+-" and not l.startswith(("+++", "---")) and marker in l]
        near = False
        for m in HUNK.finditer(diff):
            start, count = int(m[1]), int(m[2] if m[2] is not None else 1)
            lo, hi = (start, start + count - 1) if count else (start, start + 1)
            near |= any(lo <= g + ctx and hi >= g - ctx for g in gate_lines)
        if changed or near:
            hits.append(f"{gf} ({marker})")
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
