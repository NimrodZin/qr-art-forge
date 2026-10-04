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
                "FAKE_ARCH_BLOCKED", "FAKE_ROLE_BLOCKED", "FAKE_MODEL", "FAKE_TESTER_NONE", "FAKE_IMPL_NOOP",
                "FAKE_IMPL_RED", "FAKE_IMPL_UI", "FAKE_GH_NO_LABEL"):
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
    assert [s.id for s in steps][:3] == ["m2-6", "m2-7", "m2-5"]
    assert steps[0].paths == ["app.py", "tests/"] and not steps[0].touches_gpu
    assert (steps[0].cls, steps[0].lane) == ("scoped", "ordinary")          # the pilot (06 §7)
    assert steps[0].done and not steps[1].done                               # m2-7: the unattended proof (M2.9)
    assert (steps[1].cls, steps[1].lane, steps[1].touches_gpu) == ("scoped", "ordinary", True)
    assert (steps[2].cls, steps[2].lane) == ("top", "never-economize")      # bleed canvas, issue #15
    assert steps[0].gpu_env == {} and steps[2].gpu_env == {}
    assert steps[1].gpu_env == {"QRAF_VAE_SLICING": "1"}                    # m2-7: P5 flag, second GPU run


# (a2) M2.10 gpu_env ------------------------------------------------------------------------

def test_queue_line_without_gpu_env_parses_unchanged():
    s = L("queue").parse_queue(QUEUE_DOC.format(line=ORDINARY))[1]
    assert (s.id, s.title, s.paths, s.touches_gpu, s.pr_url, s.gpu_env) == \
        ("t-1", "Fake ordinary step", ["app.py", "tests/"], False, None, {})


@pytest.mark.parametrize("field,env", [
    ("gpu_env=QRAF_VAE_SLICING=1", {"QRAF_VAE_SLICING": "1"}),
    ("gpu_env=A=1;B_2=x=y", {"A": "1", "B_2": "x=y"}),
    ("gpu_env=EMPTY=", {"EMPTY": ""}),
])
def test_queue_line_with_gpu_env(tmp_path, field, env):
    q = L("queue")
    line = ORDINARY.replace("touches_gpu=no", f"touches_gpu=yes · {field}")
    plan = tmp_path / "04.md"
    plan.write_text(QUEUE_DOC.format(line=line), encoding="utf-8")
    s = q.next_step(plan)
    assert (s.id, s.title, s.touches_gpu, s.gpu_env, s.pr_url) == ("t-1", "Fake ordinary step", True, env, None)
    q.mark_done("t-1", "https://github.com/x/y/pull/8", plan)               # pr_url lands after gpu_env
    done = [s for s in q.parse_queue(plan.read_text(encoding="utf-8")) if s.id == "t-1"][0]
    assert done.done and done.gpu_env == env and done.pr_url == "https://github.com/x/y/pull/8"


@pytest.mark.parametrize("field", ["gpu_env=", "gpu_env=NOEQ", "gpu_env=1BAD=1", "gpu_env=A=1;A=2",
                                   "gpu_env=A=1;"])
def test_queue_rejects_bad_gpu_env(field):
    with pytest.raises(ValueError, match="gpu_env"):
        L("queue").parse_queue(QUEUE_DOC.format(line=ORDINARY + f" · {field}"))


GPU_ENV_CMD = ("import os; flag = os.environ.get('QRAF_VAE_SLICING') == '1'; "
               "print(os.environ['N_FLAG' if flag else 'N_DEFAULT'] + '/4 passed. Encoded: x'); "
               "print('flag=%s token=%s' % (flag, os.environ.get('HF_TOKEN', 'none')))")


@pytest.mark.parametrize("n_default,n_flag,ok", [("3", "2", True), ("1", "4", False), ("4", "1", False)])
def test_gpu_test_runs_twice_with_gpu_env(cfg, repo, monkeypatch, n_default, n_flag, ok):
    g = L("gates")
    work = repo()
    monkeypatch.setenv("N_DEFAULT", n_default)
    monkeypatch.setenv("N_FLAG", n_flag)
    monkeypatch.delenv("QRAF_VAE_SLICING", raising=False)
    cfg["gpu_cmd"] = [sys.executable, "-c", GPU_ENV_CMD]
    passed, n, tail, runs = g.gpu_test(cfg, work, {"QRAF_VAE_SLICING": "1"})
    assert passed is ok
    assert [(r["label"], r["n"], r["pass"]) for r in runs] == \
        [("default", int(n_default), int(n_default) >= 2), ("with gpu_env", int(n_flag), int(n_flag) >= 2)]
    assert "flag=False" in runs[0]["tail"] and "flag=True" in runs[1]["tail"]   # per-run tails
    failing = next((r for r in runs if not r["pass"]), runs[-1])
    assert (n, tail) == (failing["n"], failing["tail"])


def test_gpu_test_runs_once_without_gpu_env(cfg, repo, monkeypatch):
    g = L("gates")
    work = repo()
    monkeypatch.setenv("N_DEFAULT", "2")
    monkeypatch.setenv("N_FLAG", "0")
    cfg["gpu_cmd"] = [sys.executable, "-c", GPU_ENV_CMD]
    for env in (None, {}):
        passed, n, _, runs = g.gpu_test(cfg, work, env)
        assert passed and n == 2 and [r["label"] for r in runs] == ["default"]


def _comfy_script(monkeypatch, answers):
    """comfy_idle answers in order (then idle); returns the list of calls made."""
    g, seen, it = L("gates"), [], iter(answers)

    def fake(url, timeout=3.0):
        seen.append(url)
        return next(it, True)
    monkeypatch.setattr(g, "comfy_idle", fake)
    return seen


def test_gpu_test_checks_comfy_before_each_run(cfg, repo, monkeypatch):
    work = repo()
    monkeypatch.setenv("N_DEFAULT", "3")
    monkeypatch.setenv("N_FLAG", "3")
    cfg["gpu_cmd"] = [sys.executable, "-c", GPU_ENV_CMD]
    seen = _comfy_script(monkeypatch, [True, True])
    assert L("gates").gpu_test(cfg, work, {"QRAF_VAE_SLICING": "1"})[0] is True
    assert len(seen) == 2                                    # once per run
    seen = _comfy_script(monkeypatch, [True])
    L("gates").gpu_test(cfg, work)
    assert len(seen) == 1


def test_gpu_test_comfy_busy_before_second_run_stops(cfg, repo, monkeypatch, tmp_path):
    g = L("gates")
    work = repo()
    marker = tmp_path / "runs.txt"
    cfg["gpu_cmd"] = [sys.executable, "-c",
                      f"open({str(marker)!r}, 'a').write('x'); print('3/4 passed. Encoded: x')"]
    _comfy_script(monkeypatch, [True, False])               # idle before run 1, busy before run 2
    with pytest.raises(g.ComfyBusy, match="before the with gpu_env run"):
        g.gpu_test(cfg, work, {"QRAF_VAE_SLICING": "1"})
    assert marker.read_text() == "x"                         # run 1 happened, run 2 did not


@pytest.mark.parametrize("answers,which", [([False], "default"), ([True, False], "with gpu_env")])
def test_driver_stops_when_comfy_busy_before_a_gpu_run(cfg, repo, tmp_path, monkeypatch, answers, which):
    monkeypatch.setenv("N_DEFAULT", "3")
    monkeypatch.setenv("N_FLAG", "3")
    work = repo(ORDINARY.replace("touches_gpu=no", "touches_gpu=yes · gpu_env=QRAF_VAE_SLICING=1"))
    cfg["gpu_cmd"] = [sys.executable, "-c", GPU_ENV_CMD]
    _comfy_script(monkeypatch, answers)
    assert drive(cfg, work, tmp_path) == 1
    log = log_text(tmp_path)
    assert f"ComfyUI busy for 0s; GPU test not run (before the {which} run)" in log
    assert "GPU test default" not in log and "merged" not in log


def test_driver_logs_both_gpu_runs(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("N_DEFAULT", "3")
    monkeypatch.setenv("N_FLAG", "1")
    work = repo(ORDINARY.replace("touches_gpu=no", "touches_gpu=yes · gpu_env=QRAF_VAE_SLICING=1"))
    cfg["gpu_cmd"] = [sys.executable, "-c", GPU_ENV_CMD]
    assert drive(cfg, work, tmp_path) == 1
    log = log_text(tmp_path)
    assert "GPU test default 3/4 · with gpu_env 1/4 · FAIL" in log
    assert "real-generation test 1/4" in log and "flag=True" in log        # the failing run's tail


def test_driver_merges_gpu_step_when_both_runs_pass(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("N_DEFAULT", "3")
    monkeypatch.setenv("N_FLAG", "2")
    work = repo(ORDINARY.replace("touches_gpu=no", "touches_gpu=yes · gpu_env=QRAF_VAE_SLICING=1"))
    cfg["gpu_cmd"] = [sys.executable, "-c", GPU_ENV_CMD]
    assert drive(cfg, work, tmp_path) == 0
    assert "GPU test default 3/4 · with gpu_env 2/4 · pass" in log_text(tmp_path)


# (a3) M2.10 secrets ------------------------------------------------------------------------

SECRETS = ("HF_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "REJECTS_REPO")


@pytest.fixture
def secrets(monkeypatch):
    for v in SECRETS:
        monkeypatch.setenv(v, f"secret-{v}")
    monkeypatch.setenv("LOOP_NOT_SECRET", "kept")


def test_child_env_strips_secrets_unless_kept(secrets):
    sh_ = L("sh")
    assert set(sh_.SECRETS) == set(SECRETS)
    env = sh_.child_env({})
    assert not {k.upper() for k in env} & set(SECRETS)
    assert env["LOOP_NOT_SECRET"] == "kept" and env["PYTHONUTF8"] == "1"
    kept = sh_.child_env({}, keep_secrets=True)
    assert all(kept[v] == f"secret-{v}" for v in SECRETS)


def test_child_env_strips_case_blind(monkeypatch):
    monkeypatch.setattr(L("sh").os, "environ", {"hf_token": "x", "Gh_Token": "y", "PATH": "p"})
    assert L("sh").child_env({}) == {"PATH": "p", "PYTHONUTF8": "1"}


ENV_PROBE = "import os; print(sorted(v for v in %r if v in os.environ))" % (SECRETS,)


def test_run_strips_secrets_and_adds_extra_env(secrets, tmp_path):
    sh_ = L("sh")
    assert sh_.run([sys.executable, "-c", ENV_PROBE], tmp_path)[1].strip() == "[]"
    assert sh_.run([sys.executable, "-c", ENV_PROBE], tmp_path, keep_secrets=True)[1].strip() == str(sorted(SECRETS))
    out = sh_.run([sys.executable, "-c", "import os; print(os.environ['X_EXTRA'])"], tmp_path,
                  extra_env={"X_EXTRA": "on"})[1]
    assert out.strip() == "on"


def test_session_env_has_no_secrets(cfg, repo, tmp_path, secrets, monkeypatch):
    s = L("session")
    work = repo()
    seen = []
    real = s.subprocess.run

    def spy(*a, **kw):
        seen.append(kw["env"])
        return real(*a, **kw)
    monkeypatch.setattr(s.subprocess, "run", spy)
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs")
    assert not r.is_error and seen
    assert not {k.upper() for k in seen[0]} & set(SECRETS) and seen[0]["LOOP_NOT_SECRET"] == "kept"


def test_gpu_test_keeps_secrets(cfg, repo, secrets):
    work = repo()
    cfg["gpu_cmd"] = [sys.executable, "-c", "import os; print('2/4 passed. token=' + os.environ['HF_TOKEN'])"]
    ok, n, tail, _ = L("gates").gpu_test(cfg, work)
    assert ok and n == 2 and "token=secret-HF_TOKEN" in tail


def test_driver_pytest_sees_no_secrets(cfg, repo, tmp_path, secrets):
    work = repo()
    (work / "tests" / "test_env.py").write_text(
        "import os\n\n\ndef test_no_secrets():\n"
        f"    assert not [v for v in {SECRETS!r} if v in os.environ]\n")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-q", "-m", "env probe")
    sh(work, "git", "push", "-q", "origin", "main")
    assert drive(cfg, work, tmp_path) == 0                  # suite after commit and on main stay green
    assert "suite red" not in log_text(tmp_path)


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


def test_session_header_missing_is_advisory(cfg, repo, tmp_path, monkeypatch):
    s = L("session")
    work = repo()
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs")
    assert not r.is_error and r.header_ok is True
    monkeypatch.setenv("FAKE_NO_HEADER", "1")
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs", 2)
    assert not r.is_error and r.error == "" and r.header_ok is False
    assert r.text.splitlines()[0] == "APPROVE"


def test_session_wrong_model_is_error(cfg, repo, tmp_path, monkeypatch):
    s = L("session")
    work = repo()
    monkeypatch.setenv("FAKE_MODEL", "claude-sonnet-5")                  # reviewer is top → opus
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs")
    assert r.is_error and "wrong model" in r.error
    monkeypatch.setenv("FAKE_MODEL", "claude-opus-5-5")                  # scoped implementer → sonnet
    r = s.run_role("implementer", _step(), {"spec": "s"}, cfg, work, tmp_path / "runs")
    assert r.is_error and "wrong model" in r.error
    monkeypatch.setenv("FAKE_MODEL", "claude-opus-5-5,claude-haiku-4-5-20251001")   # pinned + helper
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs", 2)
    assert not r.is_error and r.error == ""


def test_session_marks_blocked_reply_without_error(cfg, repo, tmp_path, monkeypatch):
    s = L("session")
    work = repo()
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs")
    assert not r.is_error and r.blocked is False
    monkeypatch.setenv("FAKE_ROLE_BLOCKED", "reviewer")
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs", 2)
    assert not r.is_error and r.blocked is True
    assert r.text.splitlines()[1] == "BLOCKED: fake reason"
    monkeypatch.setenv("FAKE_NO_HEADER", "1")
    r = s.run_role("reviewer", _step(), {"spec": "s", "diff": "d"}, cfg, work, tmp_path / "runs", 3)
    assert not r.is_error and r.blocked is True and r.header_ok is False
    assert r.text.splitlines()[0] == "BLOCKED: fake reason"


H = "Class: top · Step: t-1"


@pytest.mark.parametrize("text,blocked", [
    ("BLOCKED: no spec\n\nwhy", True),
    (f"{H}\nBLOCKED: no spec\n\nwhy", True),
    (f"{H}\n\n**BLOCKED: no spec**", True),
    ("\n\nBLOCKED: t-1 needs a top-class answer", True),    # names class and step, still not a header
    (f"{H}\nDone.\n\nBLOCKED: later line", False),
    ("Done.\nBLOCKED: line 2 of a headerless reply", False),
    (f"{H}\nAPPROVE", False),
])
def test_is_blocked_with_or_without_header(text, blocked):
    assert L("session").is_blocked(text, "top", "t-1") is blocked


def test_strip_header_removes_only_the_header_line():
    s = L("session")
    assert s.strip_header(f"{H}\nAPPROVE\n", "top", "t-1").strip() == "APPROVE"
    assert s.strip_header("APPROVE\nmore\n", "top", "t-1").strip() == "APPROVE\nmore"
    assert s.strip_header("Class: scoped · Step: t-1\nAPPROVE", "top", "t-1").startswith("Class: scoped")


@pytest.mark.parametrize("text,approved", [
    ("APPROVE\n\n## Handover\n- Not certain: None", True),
    (f"{H}\nAPPROVE\n\n## Handover\n- Not certain: None", True),
    (f"{H}\n\n**APPROVE**", True),
    ("1. app.py:3 wrong default.\n2. tests pin nothing.", False),
    (f"{H}\n1. app.py:3 wrong default.\n2. tests pin nothing.", False),
    (f"{H}\n", False),
    ("", False),
])
def test_parse_verdict_with_or_without_header(text, approved):
    ok, body = L("run").parse_verdict(text, "top", "t-1")
    assert ok is approved
    if not approved:
        assert body and "Class: top" not in body
    if "app.py:3" in text:
        assert body.splitlines()[0] == "1. app.py:3 wrong default."


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


@pytest.mark.parametrize("head", ["", H + "\n"])
def test_blocking_unaffected_by_missing_header(head):
    run = L("run")
    assert run.blocking(head + "## Scope\nx\n\n## 5. Blocking questions\nNone\n") == ""
    got = run.blocking(head + "## Scope\nx\n\n## 5. Blocking questions\nB1: docs/02? A or B.\n")
    assert "B1: docs/02? A or B." in got


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


# never-economize lane (06 §3 v0.6): open in config + every hit named by the step's paths

NE = ORDINARY.replace("lane=ordinary", "lane=never-economize")


@pytest.mark.parametrize("lane, paths, hits, is_open, refused", [
    ("never-economize", ["validator.py", "tests/"], ["validator.py"], True, ""),                # (b) path
    ("never-economize", ["app.py", "tests/"], ["app.py (gate)"], True, ""),                     # (b) gate
    ("never-economize", [".github/", "tests/"], [".github/workflows/ci.yml"], True, ""),        # prefix
    ("never-economize", ["app.py"], [], True, ""),                                              # no hit
    ("never-economize", ["validator.py"], ["validator.py"], False, "lane closed"),
    ("never-economize", ["validator.py"], ["validator.py"], None, "lane closed"),              # key absent
    ("never-economize", ["validator.py"], ["validator.py"], "true", "lane closed"),            # not a bool
    ("never-economize", ["app.py"], [], False, "lane closed"),
    ("never-economize", ["validator.py"], ["qrbuild.py", "validator.py"], True, "not named in the spec: qrbuild.py"),
    ("never-economize", [".github"], [".github/w.yml"], True, "not named in the spec: .github/w.yml"),
    ("never-economize", ["validator"], ["validator.py"], True, "not named in the spec: validator.py"),
    ("ordinary", ["validator.py", "tests/"], ["validator.py"], True, "diff touches never-economize validator.py"),
    ("ordinary", ["app.py"], [], True, ""),
])
def test_merge_refusal(cfg, lane, paths, hits, is_open, refused):
    ne = {k: v for k, v in cfg["never_economize"].items() if k != "open"}
    if is_open is not None:
        ne["open"] = is_open
    got = L("run").merge_refusal(_step(lane=lane, paths=paths), hits, dict(cfg, never_economize=ne))
    assert (refused in got) if refused else got == ""


@pytest.mark.parametrize("lane", ["never-economize", "ordinary"])
def test_merge_refusal_fail_closed_gate_refused_even_when_named(cfg, lane):
    hit = "app.py (gate: fail closed, main:app.py unreadable: SyntaxError: invalid syntax)"
    got = L("run").merge_refusal(_step(lane=lane, paths=["app.py", "tests/"]), [hit], cfg)
    assert cfg["never_economize"]["open"] is True
    assert got == "app.py gate span unresolved (base did not parse)"


def test_driver_stops_never_economize_step_on_fail_closed_gate(cfg, repo, tmp_path):
    work = repo(NE)                                     # paths=app.py,tests/ — app.py is named
    (work / "app.py").write_text("def forge(:\n")       # base app.py does not parse
    sh(work, "git", "commit", "-q", "-am", "broken base")
    sh(work, "git", "push", "-q", "origin", "main")
    assert drive(cfg, work, tmp_path) == 1
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert not any(a[:2] == ["pr", "merge"] for a in gh)
    assert ["pr", "edit", "7", "--add-label", "needs-nimrod"] in gh
    assert "app.py gate span unresolved (base did not parse)" in _issue_body(tmp_path)


def test_config_opens_the_never_economize_lane(cfg):
    assert cfg["never_economize"]["open"] is True       # 07 v0.2 verdict yes (Nimrod, 2026-10-03)


def test_driver_merges_never_economize_step_when_open_and_named(cfg, repo, tmp_path):
    work = repo(NE.replace("paths=app.py,tests/", "paths=validator.py,tests/"))
    assert drive(cfg, work, tmp_path) == 0
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert ["pr", "merge", "7", "--squash", "--delete-branch"] in gh
    assert not any("needs-nimrod" in a for a in gh)
    assert "hits named in the spec: validator.py" in log_text(tmp_path)


def test_driver_merges_never_economize_gate_hit_when_app_named(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(L("gates"), "touched_never_economize", lambda *a, **k: ["app.py (gate)"])
    work = repo(NE)
    assert drive(cfg, work, tmp_path) == 0
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert ["pr", "merge", "7", "--squash", "--delete-branch"] in gh


def test_driver_stops_never_economize_step_when_lane_closed(cfg, repo, tmp_path):
    cfg["never_economize"] = dict(cfg["never_economize"], open=False)
    work = repo(NE.replace("paths=app.py,tests/", "paths=validator.py,tests/"))
    assert drive(cfg, work, tmp_path) == 1
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert not any(a[:2] == ["pr", "merge"] for a in gh)
    assert ["pr", "edit", "7", "--add-label", "needs-nimrod"] in gh
    assert "lane closed" in _issue_body(tmp_path) and "lane closed" in log_text(tmp_path)


def test_driver_stops_never_economize_step_on_unnamed_hit(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(L("gates"), "touched_never_economize",
                        lambda *a, **k: [".github/workflows/ci.yml", "validator.py"])
    work = repo(NE.replace("paths=app.py,tests/", "paths=validator.py,tests/"))
    assert drive(cfg, work, tmp_path) == 1
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert not any(a[:2] == ["pr", "merge"] for a in gh)
    assert ["pr", "edit", "7", "--add-label", "needs-nimrod"] in gh
    assert "not named in the spec: .github/workflows/ci.yml)" in _issue_body(tmp_path)   # validator.py is named


def test_driver_ordinary_step_with_hit_still_stops_when_lane_open(cfg, repo, tmp_path):
    assert cfg["never_economize"]["open"] is True
    work = repo(ORDINARY.replace("paths=app.py,tests/", "paths=validator.py,tests/"))
    assert drive(cfg, work, tmp_path) == 1
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert not any(a[:2] == ["pr", "merge"] for a in gh)
    assert "diff touches never-economize validator.py" in _issue_body(tmp_path)


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
    monkeypatch.setenv("FAKE_MODEL", "claude-haiku-4-5-20251001")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert "architect session error: wrong model" in log_text(tmp_path)
    body = _issue_body(tmp_path)
    assert "session error" in body
    assert "Fake spec for t-1" in body and "Blocking questions: None" in body


def test_driver_header_missing_is_advisory(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_NO_HEADER", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 0          # headerless APPROVE still approves
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect", "tester", "implementer", "reviewer"]
    log = log_text(tmp_path)
    assert log.count("header missing (advisory)") == 4
    assert "session error" not in log and "review APPROVE" in log and "merged" in log


def test_driver_stops_when_headerless_tester_blocks(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_NO_HEADER", "1")
    monkeypatch.setenv("FAKE_ROLE_BLOCKED", "tester")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert "STOP · tester blocked" in log_text(tmp_path)
    assert "BLOCKED: fake reason" in _issue_body(tmp_path)


def test_driver_stops_architect_block_without_header(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_NO_HEADER", "1")
    monkeypatch.setenv("FAKE_ARCH_BLOCKED", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect"]
    log = log_text(tmp_path)
    assert "STOP · architect blocked" in log and "session error" not in log
    assert "B1: fake question" in _issue_body(tmp_path)


# (h) M2.8 fixes from the pilot (loop/runs/m2-6/log.md) ----------------------------------------

def _order(tmp_path):
    """Stage lines of the step log, without timestamps."""
    return [l.split(" · ", 1)[1] for l in log_text(tmp_path).splitlines()]


def test_driver_suite_red_after_commit_goes_back_without_push(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_IMPL_RED", "first")         # attempt 1 leaves the suite red, attempt 2 fixes it
    work = repo()
    assert drive(cfg, work, tmp_path) == 0
    roles = [c["role"] for c in calls(tmp_path, "claude.jsonl")]
    assert roles == ["architect", "tester", "implementer", "implementer", "reviewer"]   # no review of attempt 1
    second = [c for c in calls(tmp_path, "claude.jsonl") if c["role"] == "implementer"][1]["stdin_prompt"]
    assert "test_loopfake" in second and "failed" in second                 # the red suite's tail is the defect list
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert sum(a[:2] == ["pr", "create"] for a in gh) == 1
    assert sum(a[:2] == ["pr", "checks"] for a in gh) == 2                 # attempt 2 + queue/state, none for 1
    order = _order(tmp_path)
    red = next(i for i, l in enumerate(order) if l.startswith("suite red after commit"))
    pr = next(i for i, l in enumerate(order) if l.startswith("PR "))
    assert red < pr                                                          # no push before the suite is green
    msgs = sh(work, "git", "log", "--format=%s", "loop/t-1")
    assert "implementation (attempt 1)" in msgs and "implementation (attempt 2)" in msgs


def test_driver_suite_red_on_every_attempt_stops_without_pr(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_IMPL_RED", "always")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect", "tester", "implementer", "implementer"]
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert not any(a[:2] in (["pr", "create"], ["pr", "checks"], ["pr", "merge"]) for a in gh)
    assert "2 implementer attempts" in log_text(tmp_path)
    assert sh(work, "git", "ls-remote", "origin", "loop/t-1").strip() == ""      # never pushed


def test_driver_suite_deselects_gpu_tests(cfg, repo, tmp_path):
    work = repo()
    (work / "tests" / "test_gpu_only.py").write_text(
        "import pytest\n\n\n@pytest.mark.gpu\ndef test_needs_the_4070():\n    assert False\n")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-q", "-m", "gpu test")
    sh(work, "git", "push", "-q", "origin", "main")
    assert drive(cfg, work, tmp_path) == 0                  # suite after commit and on main run -m "not gpu"
    assert "suite red" not in log_text(tmp_path)


def test_driver_ci_red_sends_failed_log_to_implementer(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_GH_CHECKS", "fail")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    runs = [a for a in gh if a[:2] == ["run", "list"]]
    assert runs and _flag(runs[0], "--branch") == "loop/t-1"
    assert ["run", "view", "4242", "--log-failed"] in gh                    # the latest run id from `run list`
    second = [c for c in calls(tmp_path, "claude.jsonl") if c["role"] == "implementer"][1]["stdin_prompt"]
    assert "fake failed log line 99" in second and "fake failed log line 40" in second
    assert "fake failed log line 39" not in second                           # last 60 lines only


def test_driver_stops_when_implementer_changes_nothing(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_IMPL_NOOP", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert [c["role"] for c in calls(tmp_path, "claude.jsonl")] == ["architect", "tester", "implementer"]
    assert "STOP · implementer made no change" in log_text(tmp_path)
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert not any(a[:2] in (["pr", "create"], ["pr", "checks"]) for a in gh)
    assert "**Reason:** implementer made no change" in _issue_body(tmp_path)
    assert sh(work, "git", "ls-remote", "origin", "loop/t-1").strip() == ""


def test_driver_tester_no_test_files_stop_carries_reply(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_TESTER_NONE", "1")
    work = repo()
    assert drive(cfg, work, tmp_path) == 1
    assert "STOP · tester wrote no test files" in log_text(tmp_path)
    body = _issue_body(tmp_path)
    assert "**Reason:** tester wrote no test files" in body
    assert "The fake tester wrote no tests: nothing in the spec is testable." in body
    assert "loop/runs/t-1/tester-1.json" in body


def test_ui_strings_from_added_app_lines(cfg, repo):
    g = L("gates")
    work = repo()
    sh(work, "git", "checkout", "-q", "-b", "x")
    app = work / "app.py"
    app.write_text(app.read_text() +
                   'box = gr.Textbox(label="Negative prompt", placeholder="e.g. text")\n'
                   'gr.Markdown("Failed generations may be stored.")\n'
                   "n = 2  # no UI string\n")
    (work / "other.py").write_text('x = gr.Textbox(label="not app.py")\n')
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-qm", "ui")
    assert g.ui_strings(work, "main") == ['box = gr.Textbox(label="Negative prompt", placeholder="e.g. text")',
                                          'gr.Markdown("Failed generations may be stored.")']


def test_driver_flags_ui_change_in_pr_body_and_label(cfg, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_IMPL_UI", "1")
    monkeypatch.setenv("FAKE_GH_NO_LABEL", "ui-change")      # label missing on the repo → driver creates it
    work = repo()
    assert drive(cfg, work, tmp_path) == 0                   # auto-merge unaffected
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    body = _flag([a for a in gh if a[:2] == ["pr", "create"]][0], "--body")
    assert "UI change — approve by seeing" in body
    assert 'label="Fake label"' in body and 'gr.Markdown("Fake UI note")' in body
    create = [i for i, a in enumerate(gh) if a[:3] == ["label", "create", "ui-change"]]
    added = [i for i, a in enumerate(gh) if a[:2] == ["pr", "edit"] and a[-2:] == ["--add-label", "ui-change"]]
    assert create and added and added[-1] > create[0]
    assert ["pr", "merge", "7", "--squash", "--delete-branch"] in gh


def test_driver_no_ui_flag_without_ui_strings(cfg, repo, tmp_path):
    work = repo()
    assert drive(cfg, work, tmp_path) == 0
    gh = [c["argv"] for c in calls(tmp_path, "gh.jsonl")]
    assert "UI change" not in _flag([a for a in gh if a[:2] == ["pr", "create"]][0], "--body")
    assert not any("ui-change" in a for a in gh)


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
    assert g.touched_never_economize(cfg, work) == ["app.py (gate)"]
    (work / "validator.py").write_text("x = 1\n")
    (work / ".github").mkdir()
    (work / ".github" / "w.yml").write_text("on: push\n")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-qm", "ne")
    assert set(g.touched_never_economize(cfg, work)) == {".github/w.yml", "validator.py", "app.py (gate)"}


# (g2) M2.10 gate spans ----------------------------------------------------------------------

GATE_APP = [
    "import os",                                          # 1
    "from validator import validate, summary_line",       # 2
    "",                                                   # 3
    "",                                                   # 4
    "def helper():",                                      # 5
    "    return 1",                                       # 6
    "",                                                   # 7
    "",                                                   # 8
    "def run_forge(cands, out):",                         # 9
    "    a = 1",                                          # 10
    "    b = 2",                                          # 11
    "    c = 3",                                          # 12
    "    d = 4",                                          # 13
    "    e = 5",                                          # 14
    "    for v in cands:",                                # 15
    "        if v['pass']:  # THE GATE",                  # 16
    "            out.append(v)",                          # 17
    "    return out",                                     # 18
    "",                                                   # 19
    "",                                                   # 20
    "@decorate",                                          # 21
    "def forge(cands):",                                  # 22
    "    return run_forge(cands, [])",                    # 23
    "",                                                   # 24
    "",                                                   # 25
    "def other():",                                       # 26
    "    x = 1",                                          # 27
    "    y = 2",                                          # 28
    "    z = 3",                                          # 29
    "    w = 4",                                          # 30
    "    v = 5",                                          # 31
    "    u = 6",                                          # 32
    "    t = 7",                                          # 33
    "    s = 8",                                          # 34
    "    r = 9",                                          # 35
    "    q = 10",                                         # 36
    "    p = 11",                                         # 37
    "    o = 12",                                         # 38
    "    n = 13",                                         # 39
    "    m = 14",                                         # 40
    "    return x",                                       # 41
    "",                                                   # 42
    "",                                                   # 43
    'NOTE = "Failed generations may be stored."  # DISCLOSURE',  # 44
    "",                                                   # 45
    "",                                                   # 46
    "",                                                   # 47
    "",                                                   # 48
    "END = 0",                                            # 49
]


def _gate_repo(repo, base_lines=GATE_APP):
    """Commit base_lines as app.py on main, then branch `x` off it."""
    work = repo()
    (work / "app.py").write_text("\n".join(base_lines) + "\n")
    sh(work, "git", "commit", "-qam", "gate app")
    sh(work, "git", "checkout", "-q", "-b", "x")
    return work


def _edit_app(work, lineno, new=None, insert=None):
    lines = (work / "app.py").read_text().splitlines()
    if new is not None:
        lines[lineno - 1] = new
    if insert is not None:
        lines.insert(lineno, insert)                      # after base line `lineno`
    (work / "app.py").write_text("\n".join(lines) + "\n")
    sh(work, "git", "commit", "-qam", f"edit {lineno}")


def test_gate_spans_from_ast():
    spans = L("gates").gate_spans("\n".join(GATE_APP) + "\n", ["run_forge", "forge"])
    assert sorted(spans) == [(2, 2), (9, 18), (21, 23)]   # import line, run_forge, forge with decorator


@pytest.mark.parametrize("lineno,new,insert,hit", [
    (11, "    b = 22", None, True),                       # inside run_forge, > 3 lines from the marker
    (18, None, "    out.sort()", True),                   # appended to run_forge's last line
    (21, "@other_decorator", None, True),                 # forge's decorator
    (23, "    return run_forge(cands, [1])", None, True),  # forge body
    (2, "from validator import validate", None, True),    # validator import line
    (1, "import os, sys", None, False),                   # a plain import
    (6, "    return 2", None, False),                     # helper, outside every span
    (34, "    s = 80", None, False),                      # other(), far from both markers
    (34, "    s = 8  # DISCLOSURE moved here", None, True),  # changed line carries a marker
    (47, "EXTRA = 1", None, True),                        # within ±3 of the DISCLOSURE line on base
    (48, "EXTRA = 1", None, False),                       # 4 lines away: outside ±3
])
def test_gate_span_and_marker_hits(cfg, repo, lineno, new, insert, hit):
    g = L("gates")
    work = _gate_repo(repo)
    _edit_app(work, lineno, new, insert)
    assert g.touched_never_economize(cfg, work) == (["app.py (gate)"] if hit else [])


def test_gate_spans_come_from_base(cfg, repo):
    g = L("gates")
    work = _gate_repo(repo)
    _edit_app(work, 6, insert="import validator")           # an import added outside base's spans
    assert g.touched_never_economize(cfg, work) == []
    _edit_app(work, 2, new="from validator import validate as v2")   # base's import line itself
    assert g.touched_never_economize(cfg, work) == ["app.py (gate)"]


@pytest.mark.parametrize("lineno,new,insert,hit", [
    (0, None, 'validate = lambda *a: {"pass": True}', True),   # module-level rebinding at the top
    (34, "    s = validate(8, 'x')", None, True),              # token in other(), far from every span
    (6, "    return 2  # validate later", None, True),         # token in a comment still counts
    (34, "    s = revalidated_count", None, False),            # no word boundary: not the token
    (34, "    s = _validate", None, False),
])
def test_gate_validate_token_outside_spans(cfg, repo, lineno, new, insert, hit):
    work = _gate_repo(repo)
    _edit_app(work, lineno, new, insert)
    assert L("gates").touched_never_economize(cfg, work) == (["app.py (gate)"] if hit else [])


def test_gate_validate_token_on_removed_line(cfg, repo):
    lines = GATE_APP[:40] + ["    k = validate"] + GATE_APP[40:]   # inside other(), outside every span
    work = _gate_repo(repo, lines)
    _edit_app(work, 41, "    k = 0")
    assert L("gates").touched_never_economize(cfg, work) == ["app.py (gate)"]


def test_gate_marker_config_as_string_still_works(cfg, repo):
    cfg["never_economize"] = dict(cfg["never_economize"], gate_marker="THE GATE")
    work = _gate_repo(repo)
    _edit_app(work, 34, "    s = 8  # DISCLOSURE")         # DISCLOSURE is not a marker in this config
    assert L("gates").touched_never_economize(cfg, work) == []


@pytest.mark.parametrize("base,why", [
    (["def forge(:", "    pass", "x = 1"], "SyntaxError"),             # base app.py does not parse
    (["def renamed():", "    pass", "x = 1"], "LookupError"),          # no gate function on base
])
def test_gate_fails_closed_when_base_unreadable(cfg, repo, base, why):
    work = _gate_repo(repo, base)
    _edit_app(work, 3, "x = 2")                                        # far from anything, harmless
    (hit,) = L("gates").touched_never_economize(cfg, work)
    assert hit.startswith("app.py (gate: fail closed") and why in hit


def test_gate_not_checked_when_app_untouched(cfg, repo):
    work = _gate_repo(repo, ["def forge(:"])                           # unparsable, but app.py unchanged
    (work / "other.py").write_text("x = 1\n")
    sh(work, "git", "add", "-A")
    sh(work, "git", "commit", "-qm", "other")
    assert L("gates").touched_never_economize(cfg, work) == []


def test_real_app_parses_with_both_gate_functions(cfg):
    src = subprocess.run(["git", "show", "HEAD:app.py"], cwd=ROOT, check=True, capture_output=True).stdout.decode()
    spans = L("gates").gate_spans(src, cfg["never_economize"]["gate_functions"])
    assert len([s for s in spans if s[1] > s[0]]) == 2                  # run_forge and forge
    assert any(s[0] == s[1] for s in spans)                             # `from validator import ...`


def test_ci_green_reads_buckets(cfg, monkeypatch):
    g = L("gates")
    assert g.ci_green(7, cfg) is True
    monkeypatch.setenv("FAKE_GH_CHECKS", "fail")
    assert g.ci_green(7, cfg) is False
    monkeypatch.setenv("FAKE_GH_CHECKS", "pending")
    assert g.ci_green(7, cfg) is False                              # timeout 0 → not green
