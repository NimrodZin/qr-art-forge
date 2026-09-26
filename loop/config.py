"""Load loop/config.toml, with LOOP_CLAUDE_CMD / LOOP_GH_CMD environment overrides."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "config.toml"


def load_config(path: Path | str | None = None) -> dict:
    with open(path or CONFIG, "rb") as f:
        cfg = tomllib.load(f)
    for var, key in (("LOOP_CLAUDE_CMD", "claude_cmd"), ("LOOP_GH_CMD", "gh_cmd")):
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    return cfg
