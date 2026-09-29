"""loop/ orchestrator (docs/06_Loop_Spec.md): queue, session flags, gates, driver.

No network, no GPU, no real remote: the driver runs in a temp git repo whose `origin` is a
local bare repo; `claude` and `gh` are loop/fake_claude.py and loop/fake_gh.py.
"""
import datetime
import http.server
import importlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FAKE_CLAUDE = str(ROOT / "loop" / "fake_claude.py")
FAKE_GH = str(ROOT / "loop" / "fake_gh.py")


def L(name):
    """Import loop.<name> inside each test, so a missing module fails tests one by one."""
    return importlib.import_module(f"loop.{name}")


QUEUE_DOC = """# 04 — Build Plan

## M2
Steps: prose, not queue.

## Queue
- [x] t-0 · Already done · class=scoped · lane=ordinary · paths=app.py · touches_gpu=no · https://github.com/x/y/pull/1
- [ ] {line}
- [ ] t-9 · Later step · class=cheap · lane=ordinary · paths=app.py,tests/ · touches_gpu=no

## Gate log
- nothing
"""

ORDINARY = "t-1 · Fake ordinary step · class=scoped · lane=ordinary · paths=app.py,tests/ · touches_gpu=no"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    """A temp repo on main with a local bare `origin`; call it with the queue line under test."""
    def make(line=ORDINARY):
        bare, work = tmp_path / "origin.git", tmp_path / "work"
        sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(bare))
        sh(tmp_path, "git", "init", "-q", "-b", "main", str(work))
        sh(work, "git", "config", "user.email", "loop@test")
        sh(work, "git", "config", "user.name", "loop test")
        sh(work, "git", "config", "core.autocrlf", "false")
        (work / "docs").mkdir()
        (work / "docs" / "04_Build_Plan.md").write_text(QUEUE_DOC.format(line=line), encoding="utf-8")
        (work / "tests").mkdir()
        (work / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
        (work / "app.py").write_text(
            "def forge(v, out):\n"
            "    if v['pass']:  # THE GATE — the only way into the gallery\n"
            "        out.append(v)\n"
            "\n\n\n\n\n\n"
            "def other():\n"
            "    return 1\n")
        (work / "validator.py").write_text("def validate():\n    return {'pass': False}\n")
        (work / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
        sh(work, "git", "add", "-A")
        sh(work, "git", "commit", "-q", "-m", "init")
        sh(work, "git", "remote", "add", "origin", str(bare))
        sh(work, "git", "push", "-q", "-u", "origin", "main")
        return work
    return make


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "claude.jsonl"))
    monkeypatch.setenv("FAKE_GH_LOG", str(tmp_path / "gh.jsonl"))
    for var in ("FAKE_REVIEW", "FAKE_NO_HEADER", "FAKE_TESTER_GREEN", "FAKE_IMPL_ESCAPE", "FAKE_GH_CHECKS",
                "FAKE_ARCH_BLOCKED", "FAKE_ROLE_BLOCKED"):
        monkeypatch.delenv(var, raising=False)
    c = L("config").load_config()
    c.update(claude_cmd=[sys.executable, FAKE_CLAUDE], gh_cmd=[sys.executable, FAKE_GH],
             pytest_cmd=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
             gpu_cmd=[sys.executable, "-c", "print('3/4 passed. Encoded: x')"],
             ci_poll_s=0, ci_timeout_s=0, comfy_wait_s=0, comfy_url="http://127.0.0.1:9",
             ca_env={})
    return c


def calls(tmp_path, name):
    p = tmp_path / name
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def drive(cfg, work, tmp_path):
    return L("run").run_loop(cfg, work, tmp_path / "runs", once=True)


def log_text(tmp_path, step_id="t-1"):
    return (tmp_path / "runs" / step_id / "log.md").read_text(encoding="utf-8")


# (a) queue ------------------------------------------------------------------------------

def test_queue_parse_next_and_mark_done_round_trip(tmp_path):
    q = L("queue")
    plan = tmp_path / "04.md"
    plan.write_text(QUEUE_DOC.format(line=ORDINARY), encoding="utf-8")
    steps = q.parse_queue(plan.read_text(encoding="utf-8"))
    assert [s.id for s in steps] == ["t-0", "t-1", "t-9"]
    assert steps[0].done and steps[0].pr_url == "https://github.com/x/y/pull/1"
    s = q.next_step(plan)
    assert (s.id, s.title, s.cls, s.lane, s.paths, s.touches_gpu, s.done) == \
        ("t-1", "Fake ordinary step", "scoped", "ordinary", ["app.py", "tests/"], False, False)
    q.mark_done("t-1", "https://github.com/x/y/pull/7", plan)
    text = plan.read_text(encoding="utf-8")
    assert f"- [x] {ORDINARY} · https://github.com/x/y/pull/7\n" in text
    assert "## Gate log\n- nothing" in text          # the rest of the file is untouched
    assert q.next_step(plan).id == "t-9"
    again = [s for s in q.parse_queue(text) if s.id == "t-1"][0]
    assert again.done and again.pr_url == "https://github.com/x/y/pull/7"


def test_queue_rejects_bad_class(tmp_path):
    q = L("queue")
    with pytest.raises(ValueError):
        q.parse_queue(QUEUE_DOC.format(line=ORDINARY.replace("class=scoped", "class=huge")))


def test_real_build_plan_queue_parses():
    steps = L("queue").parse_queue((ROOT / "docs" / "04_Build_Plan.md").read_text(encoding="utf-8"))
    assert [s.id for s in steps][:3] == ["m2-6", "m2-5", "m2-7"]
    assert steps[0].paths == ["app.py", "tests/"] and not steps[0].touches_gpu
    assert (steps[0].cls, steps[0].lane) == ("scoped", "ordinary")          # the pilot (06 §7)
    assert (steps[1].cls, steps[1].lane) == ("top", "never-economize")      # bleed canvas, issue #15


# (b) session ----------------------------------------------------------------------------

def _step(**kw):
    q = L("queue")
    base = dict(id="t-1", title="T", cls="scoped", lane="ordinary", paths=["app.py", "tests/"],
                touches_gpu=False, done=False, pr_url=None)
    base.update(kw)
    return q.Step(**base)


def _flag(argv, name):
    return argv[argv.index(name) + 1]


def _flag_list(argv, name):
    i = argv.index(name) + 1
    out = []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i])
        i += 1
    return out


def test_session_flags_per_role(cfg):
    s = L("session")
    step = _step()
    for role in ("architect", "reviewer"):
        a = s.build_argv(role, step, cfg)
        assert "-p" in a and _flag(a, "--output-format") == "json"
        assert _flag(a, "--max-turns") == "40"
        assert _flag(a, "--model") == cfg["models"]["top"] == "claude-opus-5-5"
        assert _flag(a, "--permission-mode") == "dontAsk"
        assert _flag(a, "--tools") == "Read,Grep,Glob"
        assert _flag_list(a, "--allowedTools") == ["Read", "Grep", "Glob"]
        assert "--disallowedTools" not in a
    t = s.build_argv("tester", step, cfg)
    assert _flag(t, "--model") == "claude-opus-5-5"          # tester is top regardless of step class
    impl = s.build_argv("implementer", step, cfg)
    assert _flag(impl, "--model") == cfg["models"]["scoped"] == "claude-sonnet-5"
    for a in (t, impl):
        assert _flag(a, "--tools") == "Read,Grep,Glob,Edit,Write,Bash"
        allowed = _flag_list(a, "--allowedTools")
        assert "Bash(python -m pytest *)" in allowed and "Bash(git diff *)" in allowed
        assert not any(x in ("Bash", "Bash(python *)", "Bash(git *)") for x in allowed)
        assert "Bash(git push *)" in _flag_list(a, "--disallowedTools")
        assert "Bash(gh *)" in _flag_list(a, "--disallowedTools")


def test_session_runs_role_and_records(cfg, repo, tmp_path):
    work = repo()
    r = L("session").run_role("architect", _step(), {}, cfg, work, tmp_path / "runs")
    assert not r.is_error and r.text.splitlines()[0] == "Class: top · Step: t-1"
    assert r.cost_usd == pytest.approx(0.01) and r.session_id
    rec = json.loads((tmp_path / "runs" / "t-1" / "architect-1.json").read_text(encoding="utf-8"))
    assert rec["cost_usd"] == pytest.approx(0.01) and "Role: Architect" in rec["prompt"]
    assert rec["date"] == datetime.date.today().isoformat()
    (c,) = calls(tmp_path, "claude.jsonl")
    assert c["role"] == "architect" and c["stdin_prompt"]   # prompt arrives on stdin, not argv
    assert not any("Role: Architect" in x for x in c["argv"])


def test_session_rejects_missing_header(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_NO_HEADER", "1")
    r = L("session").run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, repo(), tmp_path / "runs")
    assert r.is_error and "header" in r.error


def test_session_marks_blocked_reply_without_error(cfg, repo, tmp_path, monkeypatch):
    s = L("session")
    work = repo()
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs")
    assert not r.is_error and r.blocked is False
    monkeypatch.setenv("FAKE_ROLE_BLOCKED", "reviewer")
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs", 2)
    assert not r.is_error and r.blocked is True
    assert r.text.splitlines()[1] == "BLOCKED: fake reason"


def test_every_prompt_tells_the_role_how_to_stop():
    for role in ("architect", "tester", "implementer", "reviewer"):
        text = (ROOT / "loop" / "prompts" / f"{role}.md").read_text(encoding="utf-8")
        assert "Your FINAL message must begin with the header line, even if you stop to report a problem." in text
        assert "To stop, write line 2 as `BLOCKED: <reason>`." in text


# (b2) blocking-section parse ----------------------------------------------------------------

@pytest.mark.parametrize("spec", [
    "Class: top · Step: t-1\n## Scope\nx\n\n## 5. Blocking questions\nNone\n\n## Handover\n- Not certain: y",
    "Class: top · Step: t-1\n## Scope\nx\n\n5. Blocking questions: None",
    "Class: top · Step: t-1\n## Scope\nx\n\n**Blocking questions:** None.",
    "Class: top · Step: t-1\n## Scope\nNo blocking questions arise here.\n\n## Blocking questions\n\n*None*\n",
    "Class: top · Step: t-1\n## Scope\nx",
])
def test_blocking_questions_none_is_not_blocked(spec):
    assert L("run").blocking(spec) == ""


def test_blocking_questions_section_is_returned():
    spec = ("Class: top · Step: t-1\n## Scope\nx\n\n## 5. Blocking questions\n\n"
            "**B1: this step changes docs/02.** Options: A, B.\n\n**Recommendation: A.**\n\n"
            "## Handover\n- Not certain: None\n")
    got = L("run").blocking(spec)
    assert "B1: this step changes docs/02." in got and "Recommendation: A." in got
    assert "Handover" not in got and "Not certain" not in got


def test_status_blocked_line_blocks():
    spec = "Class: top · Step: t-1\n\n**Status: BLOCKED. See §5.**\n\n## Scope\nx\n\n## Blocking questions\nNone\n"
    assert "Status: BLOCKED" in L("run").blocking(spec)


def test_excerpt_is_first_twenty_lines():
    text = "\n".join(f"line {i}" for i in range(30))
    got = L("run").excerpt(text)
    assert "line 0" in got and "line 19" in got and "line 20" not in got


# (c)–(f) driver ---------------------------------------------------------------------------

def test_driver_merges_ordinary_step_on_approve_and_green_ci(cfg, repo, tmp_path):
    work = repo()
    assert drive(cfg, work, tmp_path) == 0
    roles = [c["role"] for c in calls(tmp_path, "claude.jsonl")]
    assert roles == ["architect", "tester", "implementer", "reviewer"]
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert any(a[:2] == ["pr", "create"] for a in gh)
    assert ["pr", "merge", "7", "--squash", "--delete-branch"] in gh
    assert not any(a[:2] == ["issue", "create"] for a in gh)
    plan = sh(work, "git", "show", "loop/t-1:docs/04_Build_Plan.md")
    assert f"- [x] {ORDINARY} · https://github.com/fake/repo/pull/7" in plan
    state = sh(work, "git", "show", "loop/t-1:docs/STATE.md")
    assert "last merged t-1" in state and "next t-9" in state
    assert sh(work, "git", "show", "loop/t-1:steps/t-1/spec.md").startswith("Class: top · Step: t-1")
    assert "merged" in log_text(tmp_path)
    assert sh(work, "git", "branch", "--show-current").strip() == "main"


def test_driver_needs_nimrod_when_diff_touches_validator(cfg, repo, tmp_path):
    work = repo(ORDINARY.replace("paths=app.py,tests/", "paths=validator.py,tests/"))
    assert drive(cfg, work, tmp_path) == 1
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert not any(a[:2] == ["pr", "merge"] for a in gh)
    assert ["pr", "edit", "7", "--add-label", "needs-nimrod"] in gh
    create = [a for a in gh if a[:2] == ["issue", "create"]]
    assert create and _flag(create[0], "--title") == "loop: needs-nimrod t-1"
    assert "validator.py" in _flag(create[0], "--body")
    log = log_text(tmp_path)
    assert "needs-nimrod" in log and "validator.py" in log


def test_driver_stops_after_two_consecutive_red_reviews(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_REVIEW", "defects")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    roles = [c["role"] for c in calls(tmp_path, "claude.jsonl")]
    assert roles == ["architect", "tester", "implementer", "reviewer", "implementer", "reviewer"]
    second_impl = [c for c in calls(tmp_path, "claude.jsonl") if c["role"] == "implementer"][1]
    assert "Fake defect" in second_impl["stdin_prompt"]      # defects go to a new implementer session
    assert "2 consecutive red reviews" in log_text(tmp_path)
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert any(a[:2] == ["issue", "create"] for a in gh)
    assert not any(a[:2] == ["pr", "merge"] for a in gh)


def test_driver_stops_when_budget_exceeded(cfg, repo, tmp_path):
    work = repo()
    prev = tmp_path / "runs" / "t-0"
    prev.mkdir(parents=True)
    today = datetime.date.today().isoformat()
    ceiling = cfg["daily_cost_ceiling_usd"]
    (prev / "implementer-1.json").write_text(json.dumps({"date": today, "cost_usd": ceiling - 1.0}))
    (prev / "reviewer-1.json").write_text(json.dumps({"date": today, "cost_usd": 1.5}))
    (prev / "old-1.json").write_text(json.dumps({"date": "2000-01-01", "cost_usd": 99.0}))
    assert L("gates").budget_ok(cfg, tmp_path / "runs") == (False, pytest.approx(ceiling + 0.5))
    assert drive(cfg, work, tmp_path) == 1
    assert calls(tmp_path, "claude.jsonl") == []
    assert "budget" in log_text(tmp_path)
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert any(a[:2] == ["issue", "create"] for a in gh)


def test_driver_stops_when_tests_not_red_on_main(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TESTER_GREEN", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect", "tester"]
    assert "not red" in log_text(tmp_path)


def test_driver_stops_when_implementer_writes_tests(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_IMPL_ESCAPE", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert "outside its paths" in log_text(tmp_path)


def _issue_body(tmp_path):
    create = [c["argv"] for c in calls(tmp_path, "gh.jsonl") if c["argv"][:2] == ["issue", "create"]]
    assert create, "no needs-nimrod issue opened"
    return _flag(create[0], "--body")


def test_driver_stops_before_tester_when_architect_blocks(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ARCH_BLOCKED", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect"]
    body = _issue_body(tmp_path)
    assert "architect blocked" in body
    assert "B1: fake question touching docs/02. Options: A or B. Recommendation: A." in body
    log = log_text(tmp_path)
    assert "architect blocked" in log and "session error" not in log
    assert "B1: fake question" in (tmp_path / "runs" / "t-1" / "spec-blocked.md").read_text(encoding="utf-8")
    # nothing committed: the repo is back on a clean main with no loop branch, so a rerun can start
    assert sh(work, "git", "branch", "--show-current").strip() == "main"
    assert sh(work, "git", "status", "--porcelain").strip() == ""
    assert sh(work, "git", "branch", "--list", "loop/t-1").strip() == ""


def test_driver_proceeds_when_blocking_questions_none(cfg, repo, tmp_path):
    work = repo()
    assert drive(cfg, work, tmp_path) == 0
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect", "tester", "implementer", "reviewer"]
    assert "Blocking questions: None" in sh(work, "git", "show", "loop/t-1:steps/t-1/spec.md")
    assert "blocked" not in log_text(tmp_path)


def test_driver_stops_when_tester_blocks(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ROLE_BLOCKED", "tester")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect", "tester"]
    log = log_text(tmp_path)
    assert "STOP · tester blocked" in log and "session error" not in log
    body = _issue_body(tmp_path)
    assert "**Reason:** tester blocked" in body and "session error" not in body
    assert "BLOCKED: fake reason" in body
    assert "The fake role stopped to report instead of doing its task." in body


def test_driver_session_error_issue_carries_reply_excerpt(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_NO_HEADER", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert "architect session error: missing header" in log_text(tmp_path)
    body = _issue_body(tmp_path)
    assert "session error" in body
    assert "Fake spec for t-1" in body and "Blocking questions: None" in body


def test_driver_runs_gpu_test_for_gpu_steps(cfg, repo, tmp_path):
    work = repo(ORDINARY.replace("touches_gpu=no", "touches_gpu=yes"))
    cfg["gpu_cmd"] = [sys.executable, "-c", "print('1/4 passed. Encoded: x')"]
    assert drive(cfg, work, tmp_path) == 1
    assert "1/4" in log_text(tmp_path)


# (g) gates ------------------------------------------------------------------------------

def _serve(payload):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_comfy_idle():
    g = L("gates")
    assert g.comfy_idle("http://127.0.0.1:9") is True               # unreachable = idle
    busy = _serve({"queue_running": [[1, "abc"]], "queue_pending": []})
    idle = _serve({"queue_running": [], "queue_pending": []})
    try:
        assert g.comfy_idle(f"http://127.0.0.1:{busy.server_port}") is False
        assert g.comfy_idle(f"http://127.0.0.1:{idle.server_port}") is True
    finally:
        busy.shutdown()
        idle.shutdown()


def test_gpu_test_parses_pass_count(cfg, repo):
    g = L("gates")
    work = repo()
    cfg["gpu_cmd"] = [sys.executable, "-c", "print('2/4 passed. Encoded: x')"]
    assert g.gpu_test(cfg, work)[:2] == (True, 2)
    cfg["gpu_cmd"] = [sys.executable, "-c", "print('1/4 passed. Encoded: x')"]
    assert g.gpu_test(cfg, work)[:2] == (False, 1)


def test_touched_never_economize_paths_and_gate_line(cfg, repo):
    g = L("gates")
    work = repo()
    sh(work, "git", "checkout", "-q", "-b", "x")
    app = work / "app.py"
    app.write_text(app.read_text() + "# harmless tail\n")
    sh(work, "git", "commit", "-qam", "tail")
    assert g.touched_never_economize(cfg, work) == []
    lines = app.read_text().splitlines(keepends=True)
    lines.insert(1, "    v = {'pass': True}\n")                       # next to the gate line
    app.write_text("".join(lines))
    sh(work, "git", "commit", "-qam", "gate")
    assert g.touched_never_economize(cfg, work) == ["app.py (THE GATE)"]
    (work / "validator.py").write_text("x = 1\n")
    (work / ".github").mkdir()
    (work / ".github" / "w.yml").write_text("on: push\n")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-qm", "ne")
    assert set(g.touched_never_economize(cfg, work)) == {".github/w.yml", "validator.py", "app.py (THE GATE)"}


def test_ci_green_reads_buckets(cfg, monkeypatch):
    g = L("gates")
    assert g.ci_green(7, cfg) is True
    monkeypatch.setenv("FAKE_GH_CHECKS", "fail")
    assert g.ci_green(7, cfg) is False
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    assert g.ci_green(7, cfg) is False                              # timeout 0 → not green
