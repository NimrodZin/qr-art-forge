"""Subprocess helpers: command-line parsing, git, gh, and the environment sessions run in."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def as_argv(cmd) -> list[str]:
    """A config command is a list, or a string (env override) split shell-style.
    Backslashes become slashes first so Windows paths survive the split."""
    if isinstance(cmd, (list, tuple)):
        return [str(x) for x in cmd]
    return shlex.split(str(cmd).replace("\\", "/"))


def resolve_argv(argv: list[str], cwd: Path) -> list[str]:
    """A relative executable path (".venv/Scripts/python.exe") is taken relative to cwd."""
    exe = argv[0]
    if ("/" in exe or "\\" in exe) and not os.path.isabs(exe):
        exe = str(Path(cwd) / exe)
    return [exe, *argv[1:]]


def child_env(cfg: dict) -> dict:
    env = dict(os.environ, PYTHONUTF8="1")
    for var, path in cfg.get("ca_env", {}).items():
        if os.path.exists(path):
            env.setdefault(var, path)
    return env


def run(argv, cwd, cfg: dict | None = None, check=True, timeout=None, input=None):
    p = subprocess.run(resolve_argv(as_argv(argv), Path(cwd)), cwd=cwd, capture_output=True,
                       input=input, timeout=timeout, env=child_env(cfg or {}))
    out = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"{' '.join(as_argv(argv))} → exit {p.returncode}: {err.strip() or out.strip()}")
    return p.returncode, out, err


def git(repo, *args, check=True) -> str:
    return run(["git", *args], repo, check=check)[1]


def gh(cfg: dict, repo, *args, check=True):
    return run([*as_argv(cfg["gh_cmd"]), *args], repo, cfg, check=check)
