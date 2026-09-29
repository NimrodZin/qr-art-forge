"""One role session: `claude -p` with the prompt on stdin, JSON out, tools limited per role (06 §1).

Flags (claude 2.1.283; see loop/README.md): --tools sets which tools exist, --allowedTools
pre-approves them (Bash by command pattern), --permission-mode dontAsk denies everything else.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from loop.sh import as_argv, child_env, resolve_argv

PROMPTS = Path(__file__).resolve().parent / "prompts"
READ = ["Read", "Grep", "Glob"]
WRITE = ["Edit", "Write", "Bash"]
# Sessions test and inspect; they never commit, push, switch branches or call gh (the driver does).
BASH_ALLOW = [
    "Bash(pytest)", "Bash(pytest *)",
    "Bash(python -m pytest)", "Bash(python -m pytest *)",
    "Bash(.venv/Scripts/python.exe -m pytest)", "Bash(.venv/Scripts/python.exe -m pytest *)",
    "Bash(git status)", "Bash(git status *)", "Bash(git diff)", "Bash(git diff *)",
    "Bash(git log *)", "Bash(git show *)",
]
BASH_DENY = [
    "Bash(git push *)", "Bash(git remote *)", "Bash(git config *)", "Bash(git commit *)",
    "Bash(git checkout *)", "Bash(git switch *)", "Bash(git reset *)", "Bash(git merge *)",
    "Bash(git rebase *)", "Bash(gh *)",
]
WRITERS = ("tester", "implementer")


@dataclass
class Result:
    text: str
    cost_usd: float
    session_id: str | None
    is_error: bool
    duration_s: float
    error: str = ""
    blocked: bool = False       # the role stopped to report: line 2 is `BLOCKED: <reason>` (06 §1)


def role_class(role: str, step) -> str:
    """Architect, Tester and Reviewer are top (06 §1); the Implementer runs at the step's class."""
    return step.cls if role == "implementer" else "top"


def header(role: str, step) -> str:
    return f"Class: {role_class(role, step)} · Step: {step.id}"


def build_argv(role: str, step, cfg: dict) -> list[str]:
    tools = READ + (WRITE if role in WRITERS else [])
    allowed = READ + (["Edit", "Write", *BASH_ALLOW] if role in WRITERS else [])
    argv = [*as_argv(cfg["claude_cmd"]), "-p", "--output-format", "json",
            "--max-turns", str(cfg["max_turns"]), "--model", cfg["models"][role_class(role, step)],
            "--permission-mode", "dontAsk", "--tools", ",".join(tools), "--allowedTools", *allowed]
    if role in WRITERS:
        argv += ["--disallowedTools", *BASH_DENY]
    return argv


def render(role: str, step, extra: dict) -> str:
    text = (PROMPTS / f"{role}.md").read_text(encoding="utf-8")
    values = {"header": header(role, step), "step_id": step.id, "title": step.title,
              "class": role_class(role, step), "step_class": step.cls, "lane": step.lane,
              "paths": ",".join(step.paths), "spec": "(none)", "defects": "(none)",
              "diff": "(none)", "ci": "(unknown)",
              "gpu_test": "yes" if step.touches_gpu else "no"}
    values.update({k: v for k, v in extra.items() if v})
    # One pass, so a spec or diff that itself contains "{diff}" is not substituted again.
    return re.sub(r"\{([a-z_]+)\}", lambda m: str(values.get(m[1], m[0])), text)


def has_header(text: str, cls: str, step_id: str) -> bool:
    first = text.strip().splitlines()[0].strip("#*` ").lower() if text.strip() else ""
    word = lambda w: re.search(rf"(?<![\w-]){re.escape(w.lower())}(?![\w-])", first)
    return bool(word(cls) and word(step_id))


def is_blocked(text: str) -> bool:
    """The first non-blank line after the header starts with `BLOCKED:`."""
    body = [l for l in text.strip().splitlines()[1:] if l.strip()]
    return bool(body) and body[0].strip("#*`> ").startswith("BLOCKED:")


def run_role(role: str, step, extra_context: dict, cfg: dict, repo, runs_dir, attempt: int = 1) -> Result:
    prompt = render(role, step, extra_context)
    argv = build_argv(role, step, cfg)
    t0 = time.monotonic()
    data, raw, rc, stderr, error = None, "", None, "", ""
    try:
        p = subprocess.run(resolve_argv(argv, Path(repo)), cwd=repo, input=prompt.encode("utf-8"),
                           capture_output=True, env=child_env(cfg), timeout=cfg.get("session_timeout_s"))
        rc, raw = p.returncode, p.stdout.decode("utf-8", "replace")
        stderr = p.stderr.decode("utf-8", "replace")
        data = json.loads(raw)
    except (OSError, subprocess.TimeoutExpired) as e:
        error = f"could not run claude: {e}"
    except ValueError:
        error = f"non-JSON output (exit {rc}): {(stderr or raw).strip()[:300]}"
    data = data if isinstance(data, dict) else {}
    text = str(data.get("result") or "")
    cost = float(data.get("total_cost_usd") or 0.0)
    if not error and (data.get("is_error") or rc != 0):
        error = f"session error (exit {rc}, {data.get('subtype')}): {text[:300] or stderr.strip()[:300]}"
    if not error and not has_header(text, role_class(role, step), step.id):
        error = f"missing header line (expected '{header(role, step)}')"
    res = Result(text, cost, data.get("session_id"), bool(error), time.monotonic() - t0, error,
                 blocked=not error and is_blocked(text))
    out = Path(runs_dir) / step.id
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{role}-{attempt}.json").write_text(json.dumps({
        "date": datetime.date.today().isoformat(), "role": role, "attempt": attempt,
        "cost_usd": cost, "models": list(data.get("modelUsage") or {}), "argv": argv,
        "returncode": rc, "error": error, "stderr": stderr, "prompt": prompt,
        "response": data or raw}, indent=1, ensure_ascii=False), encoding="utf-8")
    return res
