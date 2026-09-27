"""loop/calibrate.py (docs/06 §6): seeded Phase B defects replayed against a fake Reviewer."""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKE_CLAUDE = ROOT / "loop" / "fake_claude.py"


def cal():
    return importlib.import_module("loop.calibrate")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOP_CLAUDE_CMD", f'"{sys.executable}" "{FAKE_CLAUDE}"')
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "claude.jsonl"))
    for var in ("FAKE_REVIEW", "FAKE_NO_HEADER", "FAKE_COST"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def records(runs):
    (stamp,) = [d for d in runs.iterdir() if d.is_dir() and d.name != "claude.jsonl"]
    return stamp, [json.loads(p.read_text(encoding="utf-8")) for p in sorted(stamp.glob("*.json"))]


def test_eight_seeds_each_apply_cleanly_on_head():
    seeds = cal().seeds()
    assert [n for n, _, _ in seeds] == list(range(1, 9))
    for n, slug, patch in seeds:
        p = subprocess.run(["git", "apply", "--check", "--cached", "-"], cwd=ROOT,
                           input=cal().patch_bytes(patch), capture_output=True)
        assert p.returncode == 0, f"{patch.name}: {p.stderr.decode()}"
        assert cal().patched_files(patch), patch.name


def test_fake_defect_review_catches_all_eight(fake, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_REVIEW", "defects")
    runs = fake / "runs"
    assert cal().main(["--base", "HEAD", "--runs", str(runs)]) == 0
    assert "caught 8/8" in capsys.readouterr().out
    stamp, recs = records(runs)
    assert [r["seed"] for r in recs] == list(range(1, 9)) and all(r["caught"] for r in recs)
    assert all(r["files"][0] in r["first_defect"] for r in recs)
    assert "8/8 caught" in (stamp / "summary.md").read_text(encoding="utf-8")
    prompts = [json.loads(x)["stdin_prompt"] for x in (fake / "claude.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == 8 and all("Role: Reviewer" in p and "Class: top · Step: cal-" in p for p in prompts)
    assert "+huggingface_hub" in prompts[0]                    # the real seeded diff reaches the Reviewer


def test_approving_review_catches_none(fake, capsys):
    runs = fake / "runs"
    assert cal().main(["--base", "HEAD", "--runs", str(runs)]) == 1
    assert "caught 0/8" in capsys.readouterr().out
    assert not any(r["caught"] for r in records(runs)[1])


def test_defect_not_naming_the_patched_file_is_not_caught():
    assert cal().names_file("1. README.md:12 too long", ["README.md"])
    assert not cal().names_file("1. app.py:1 does not do the thing", ["requirements-ci.txt"])


def test_cost_cap_stops_the_run(fake, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_REVIEW", "defects")
    monkeypatch.setenv("FAKE_COST", "15")
    runs = fake / "runs"
    assert cal().main(["--base", "HEAD", "--runs", str(runs), "--cap", "20"]) == 1
    out = capsys.readouterr().out
    assert "cost cap" in out and "total cost 30.00 USD" in out
    assert len(records(runs)[1]) == 2
