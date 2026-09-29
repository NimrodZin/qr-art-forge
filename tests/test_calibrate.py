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


def head_text(path):
    """The file as committed on HEAD (LF), whatever core.autocrlf did to the checkout."""
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, check=True,
                          capture_output=True).stdout.decode("utf-8")


def test_eight_seeds_are_exact_edits_whose_old_occurs_once_on_head():
    seeds = cal().seeds()
    assert [n for n, _, _ in seeds] == list(range(1, 9))
    assert not list((ROOT / "loop" / "seeds").glob("*.patch"))         # replaced by .json (M2.8)
    for n, slug, path in seeds:
        assert path.name == f"{n}-{slug}.json"
        edits = cal().load_seed(path)
        assert edits, path.name
        for e in edits:
            assert set(e) == {"file", "old", "new", "defect"}, path.name
            assert e["old"] and e["old"] != e["new"] and e["defect"], path.name
            assert head_text(e["file"]).count(e["old"]) == 1, f"{path.name}: `old` not exactly once in {e['file']}"


def test_seed_8_is_the_smallest_edit():
    (e,) = cal().load_seed(ROOT / "loop" / "seeds" / "8-gallery-not-png.json")
    assert (e["file"], e["old"], e["new"]) == ("app.py", ', format="png")', ")")


def test_apply_seed_replaces_exactly_once_or_errors(tmp_path):
    c = cal()
    (tmp_path / "a.txt").write_text("x = 1\ny = 2\n", encoding="utf-8")
    c.apply_seed([{"file": "a.txt", "old": "y = 2", "new": "y = 3", "defect": "d"}], tmp_path)
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x = 1\ny = 3\n"
    with pytest.raises(ValueError, match="0 times"):
        c.apply_seed([{"file": "a.txt", "old": "z = 9", "new": "z", "defect": "d"}], tmp_path)
    (tmp_path / "b.txt").write_text("k\nk\n", encoding="utf-8")
    with pytest.raises(ValueError, match="2 times"):
        c.apply_seed([{"file": "b.txt", "old": "k", "new": "j", "defect": "d"}], tmp_path)
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "k\nk\n"          # nothing written on error


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
