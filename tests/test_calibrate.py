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
    return stamp, [json.loads(p.read_text(encoding="utf-8"))
                   for p in sorted(stamp.glob("*.json"), key=lambda p: int(p.stem))]


def head_text(path):
    """The file as committed on HEAD (LF), whatever core.autocrlf did to the checkout."""
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, check=True,
                          capture_output=True).stdout.decode("utf-8")


def test_eleven_seeds_are_exact_edits_whose_old_occurs_once_on_head():
    seeds = cal().seeds()
    assert [n for n, _, _ in seeds] == list(range(1, 12))
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


def test_control_seeds_are_the_m2_10_edits():
    s = ROOT / "loop" / "seeds"
    got = {p: cal().load_seed(s / p)[0] for p in
           ("9-no-tilt-condition.json", "10-pass-rule-off-by-one.json", "11-quiet-zone-2.json")}
    assert [(e["file"], e["new"]) for e in got.values()] == [
        ("validator.py", "    pass  # tilt condition removed"),
        ("validator.py", '"pass": score >= len(results) - 1'),
        ("qrbuild.py", "border=2")]
    assert got["9-no-tilt-condition.json"]["old"] == \
        '    out["tilt"] = cv2.warpPerspective(img, M, (w, h), borderValue=(255, 255, 255))'
    assert got["10-pass-rule-off-by-one.json"]["old"] == '"pass": score == len(results)'
    assert got["11-quiet-zone-2.json"]["old"] == "border=4"


def test_seed_kinds():
    assert [cal().kind(n) for n in range(1, 12)] == ["listed"] * 8 + ["control"] * 3


def test_withheld_list_occurs_once_on_head(tmp_path):
    c = cal()
    text = head_text(c.WITHHOLD_FILE)
    assert text.count(c.WITHHOLD_START) == 1 and text.count(c.WITHHOLD_END) == 1
    i, j = text.index(c.WITHHOLD_START), text.index(c.WITHHOLD_END) + len(c.WITHHOLD_END)
    assert text.count(text[i:j]) == 1
    (tmp_path / "docs").mkdir()
    (tmp_path / c.WITHHOLD_FILE).write_text(text, encoding="utf-8", newline="")
    c.withhold_list(tmp_path)
    got = (tmp_path / c.WITHHOLD_FILE).read_text(encoding="utf-8")
    assert got == text[:i] + "(withheld during calibration)" + text[j:]
    for listed in ("huggingface_hub", "short_description", "deis", "OpenCV", "re-encodes"):
        assert listed not in got[got.index("## 6."):got.index("## 7.")], listed
    assert "mutation testing" in got                                   # the rest of §6 stays


@pytest.mark.parametrize("text", [
    "no list here\n",
    "1. unpinned x\n",                                                  # no end
    "1. unpinned x by a failing test.\n1. unpinned x by a failing test.\n",   # twice
])
def test_withhold_list_errors_unless_exactly_once(tmp_path, text):
    c = cal()
    (tmp_path / "docs").mkdir()
    (tmp_path / c.WITHHOLD_FILE).write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="not exactly once"):
        c.withhold_list(tmp_path)
    assert (tmp_path / c.WITHHOLD_FILE).read_text(encoding="utf-8") == text   # nothing written


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


def test_fake_defect_review_catches_all_eleven(fake, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_REVIEW", "defects")
    c = cal()
    seen = []                                                  # docs/06 §6 as the Reviewer's worktree has it
    real = c.session.run_role

    def spy(role, step, ctx, cfg, repo, out, *a):
        spec = (Path(repo) / "docs" / "06_Loop_Spec.md").read_text(encoding="utf-8")
        seen.append((spec[spec.index("## 6."):spec.index("## 7.")], ctx["diff"]))
        git = lambda *args: subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                                           text=True).stdout
        worktrees.append({
            "seeds_dir": (Path(repo) / "loop" / "seeds").exists(),
            "07": (Path(repo) / "docs" / "07_Calibration.md").exists(),
            "status": git("status", "--porcelain").strip(),
            "log": git("log", "--format=%s", "-2").split("\n")[:2],
            "prep": sorted(git("diff", "--name-status", "HEAD~2", "HEAD~1").splitlines()),
            "seed": sorted(git("diff", "--name-only", "HEAD~1", "HEAD").split()),
            "files": sorted(step.paths)})
        return real(role, step, ctx, cfg, repo, out, *a)
    worktrees = []
    monkeypatch.setattr(c.session, "run_role", spy)
    runs = fake / "runs"
    assert c.main(["--base", "HEAD", "--runs", str(runs)]) == 0
    assert "caught 11/11 (listed 8/8 · control 3/3)" in capsys.readouterr().out
    stamp, recs = records(runs)
    assert [r["seed"] for r in recs] == list(range(1, 12)) and all(r["caught"] for r in recs)
    assert [r["kind"] for r in recs] == ["listed"] * 8 + ["control"] * 3
    assert all(r["files"][0] in r["first_defect"] for r in recs)
    summary = (stamp / "summary.md").read_text(encoding="utf-8")
    assert "11/11 caught (listed 8/8 · control 3/3)" in summary and "06 §6 list withheld" in summary
    assert "| 9 no-tilt-condition | control | yes |" in summary and "| 1 huggingface-hub-unpinned | listed | yes |" in summary
    prompts = [json.loads(x)["stdin_prompt"] for x in (fake / "claude.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(prompts) == 11 and all("Role: Reviewer" in p and "Class: top · Step: cal-" in p for p in prompts)
    assert "+huggingface_hub" in prompts[0]                    # the real seeded diff reaches the Reviewer
    assert "+    pass  # tilt condition removed" in prompts[8] and "+    q = qrcode.QRCode(" in prompts[10]
    assert len(seen) == 11
    for section, diff in seen:                                 # unprimed: list withheld, and not in the diff
        assert "(withheld during calibration)" in section and "huggingface_hub" not in section
        assert "06_Loop_Spec" not in diff and "withheld" not in diff
        assert "07_Calibration" not in diff and "loop/seeds" not in diff and '"defect"' not in diff
    assert len(worktrees) == 11
    on_head = len(subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD", "loop/seeds/"], cwd=ROOT,
                                 check=True, capture_output=True, text=True).stdout.split())
    assert on_head >= 8
    for n, w in enumerate(worktrees, 1):
        assert not w["seeds_dir"] and not w["07"] and w["status"] == "", n   # removed, and committed
        assert w["log"] == [f"cal-{n}: housekeeping", f"cal-{n}: prep"]
        assert "M\tdocs/06_Loop_Spec.md" in w["prep"] and "D\tdocs/07_Calibration.md" in w["prep"]
        assert sum(l.startswith("D\tloop/seeds/") for l in w["prep"]) == on_head
        assert len(w["prep"]) == on_head + 2                   # 06 edit + 07 + every seed, nothing else
        assert w["seed"] == w["files"]                         # the seed commit is only the seed
    first_diff = seen[0][1]
    assert first_diff.count("diff --git") == 1 and "requirements-ci.txt" in first_diff


def test_approving_review_catches_none(fake, capsys):
    runs = fake / "runs"
    assert cal().main(["--base", "HEAD", "--runs", str(runs)]) == 1
    assert "caught 0/11 (listed 0/8 · control 0/3)" in capsys.readouterr().out
    assert not any(r["caught"] for r in records(runs)[1])


@pytest.mark.parametrize("missed,only,code", [
    (set(), None, 0),
    ({9}, None, 0),             # 2 of 3 controls is enough
    ({9, 11}, None, 1),         # 1 of 3 is not
    ({3}, None, 1),             # every listed seed must be caught
    ({9}, "9", 1),              # --only: a missed control is 0/1 < 2/3
    ({9}, "9,10,11", 0),
    (set(), "1,7", 0),          # --only without controls
])
def test_exit_code_listed_all_controls_two_of_three(tmp_path, monkeypatch, capsys, missed, only, code):
    c = cal()

    def fake_replay(n, slug, seed, base, cfg, out):
        return {"seed": n, "slug": slug, "kind": c.kind(n), "files": ["f"], "error": "", "caught": n not in missed,
                "first_defect": "1. f:1 x", "cost_usd": 0.0}
    monkeypatch.setattr(c, "replay", fake_replay)
    args = ["--base", "HEAD", "--runs", str(tmp_path / "runs")] + (["--only", only] if only else [])
    assert c.main(args) == code


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
