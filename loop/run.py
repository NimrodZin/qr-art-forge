"""QR Art Forge build loop driver (docs/06_Loop_Spec.md).

    python loop/run.py [--dry-run] [--once]

Per step: Architect → Tester (red on main) → [Implementer → commit → suite (red: tail to the next
attempt, no push) → push/PR → CI (red: failed log to the next attempt) → Reviewer] × attempts →
GPU test if touches_gpu → merge (APPROVE, CI green, and either ordinary lane with no
never-economize hit, or never-economize lane with config open = true and every hit named in the
step's paths) or stop PR-ready with needs-nimrod. An implementer that changes nothing stops the step. UI strings
in app.py flag the PR (body section + label `ui-change`). Any stop opens/appends issue `loop: needs-nimrod <id>`.
A role may stop instead (06 §1): `BLOCKED: <reason>` first (after the header, if given), or for the
Architect a non-empty 'Blocking questions' section; the step stops there and the reply goes into the issue.
A session's model is verified from its JSON modelUsage; the header line is advisory.
"""
from __future__ import annotations

import os
import sys

if __name__ == "__main__":  # import the package from the repo root; loop/queue.py must not shadow stdlib queue
    sys.path[0] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import argparse
import datetime
import json
import re
import tempfile
from pathlib import Path

from loop import config, gates, queue, session
from loop.sh import gh, git, run

ROOT = Path(__file__).resolve().parent.parent
LOOP = ROOT / "loop"
PLAN = Path("docs") / "04_Build_Plan.md"
SKIP = ("__pycache__/", ".pytest_cache/")


class Stop(Exception):
    """A stop condition (06 §5): the loop pauses and asks Nimrod. `detail` (markdown) goes into the issue."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.detail = detail


def within(path: str, allowed: list[str]) -> bool:
    return any(path == a.rstrip("/") or path.startswith(a.rstrip("/") + "/") for a in allowed)


def named(hit: str, paths: list[str]) -> bool:
    """A never-economize hit ("validator.py", "app.py (gate)", …) is named by the step's paths,
    with the prefix rule of gates.touched_never_economize: equal, or a path ending in "/" prefixes it."""
    path = hit.split(" (", 1)[0]
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in paths)


def merge_refusal(step, hits: list[str], cfg: dict) -> str:
    """Why the step may not auto-merge (06 §3), or "" if it may. Ordinary lane: any hit refuses.
    Never-economize lane: refused unless `[never_economize] open = true` and every hit is named.
    A fail-closed gate hit (base app.py did not parse) is refused in either lane, named or not."""
    if any("(gate: fail closed" in h for h in hits):
        return "app.py gate span unresolved (base did not parse)"
    if step.lane == "ordinary":
        return "diff touches never-economize " + ", ".join(hits) if hits else ""
    if cfg["never_economize"].get("open") is not True:
        return f"lane={step.lane}, lane closed (config never_economize.open is not true)"
    unnamed = [h for h in hits if not named(h, step.paths)]
    if unnamed:
        return f"lane={step.lane}, diff touches never-economize not named in the spec: " + ", ".join(unnamed)
    return ""


def parse_verdict(text: str, cls: str, step_id: str) -> tuple[bool, str]:
    """The first non-blank line after the header (if given) is `APPROVE` or the defect list."""
    body = session.strip_header(text.split("## Handover")[0], cls, step_id).splitlines()
    body = [l for l in body if l.strip()]
    if body and body[0].strip().strip("*`").strip() == "APPROVE":
        return True, ""
    return False, "\n".join(body) or "(reviewer gave no verdict)"


STATUS_BLOCKED = re.compile(r"^[#*_>\s]*status\s*:\s*[*_]*\s*blocked\b", re.I)
QUESTIONS = re.compile(r"^(#*)[*_\s]*(?:\d+\.\s*)?[*_]*blocking questions\b[*_:\s]*(.*)$", re.I)
HEADING = re.compile(r"^(#{1,6})\s")


def blocking(spec: str) -> str:
    """The Architect's block (06 §1): a line `Status: BLOCKED`, or a 'Blocking questions' section
    whose text is anything other than `None`. Returns what blocks, or "" if nothing does."""
    lines = spec.split("## Handover")[0].splitlines()
    found = [l.strip() for l in lines if STATUS_BLOCKED.match(l)]
    for i, line in enumerate(lines):
        m = QUESTIONS.match(line)
        if not m:
            continue
        level = len(m[1]) or 6        # the section ends at the next heading of its level or above
        body = [m[2]] if m[2].strip() else []
        if not body:
            for l in lines[i + 1:]:
                h = HEADING.match(l)
                if h and len(h[1]) <= level:
                    break
                body.append(l)
        text = "\n".join(body).strip()
        if text.strip("*_. ").lower() not in ("", "none"):
            found += [line.strip(), text]
        break
    return "\n\n".join(found)


def excerpt(text: str, n: int = 20) -> str:
    lines = text.strip().splitlines()
    more = f"\n… ({len(lines) - n} more lines)" if len(lines) > n else ""
    return "\n".join(lines[:n]) + more


def quoted(title: str, text: str) -> str:
    return f"**{title}:**\n\n" + "\n".join("> " + l for l in text.splitlines())


class Driver:
    def __init__(self, cfg: dict, repo, runs_dir):
        self.cfg, self.repo, self.runs = cfg, Path(repo), Path(runs_dir)
        self.base = cfg.get("base_branch", "main")
        self.pr_url = None
        self.ui: list[str] = []

    # -- bookkeeping ---------------------------------------------------------------------
    def log(self, step, msg: str) -> None:
        d = self.runs / step.id
        d.mkdir(parents=True, exist_ok=True)
        line = f"- {datetime.datetime.now().isoformat(timespec='seconds')} · {msg}"
        with open(d / "log.md", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(f"[{step.id}] {line[2:]}", flush=True)

    def steps_started_today(self) -> int:
        today = f"- {datetime.date.today().isoformat()}"
        return sum(any(l.startswith(today) and "step start" in l
                       for l in f.read_text(encoding="utf-8").splitlines())
                   for f in self.runs.glob("*/log.md"))

    def check_budget(self) -> None:
        ok, spent = gates.budget_ok(self.cfg, self.runs)
        if not ok:
            raise Stop(f"cap: daily budget — spent {spent:.2f} of {self.cfg['daily_cost_ceiling_usd']} USD today")

    # -- git -----------------------------------------------------------------------------
    def changed(self) -> list[str]:
        out = git(self.repo, "status", "--porcelain", "-uall")
        paths = [l[3:].split(" -> ")[-1].strip('"') for l in out.splitlines() if l.strip()]
        return [p for p in paths if not any(s in p for s in SKIP)]

    def expect_changes(self, step, role: str, allowed: list[str]) -> list[str]:
        paths = self.changed()
        outside = [p for p in paths if not within(p, allowed)]
        if outside:
            raise Stop(f"{role} wrote outside its paths {allowed or '(none)'}: {', '.join(outside)}")
        return paths

    def commit(self, paths: list[str], what: str, step) -> None:
        git(self.repo, "add", "-A", "--", *paths)
        git(self.repo, "commit", "-q", "-m", f"loop {step.id}: {what}")

    def push(self, branch: str) -> None:
        git(self.repo, "push", "-q", "-u", "origin", branch)

    @property
    def pr(self) -> str:
        return self.pr_url.rstrip("/").rsplit("/", 1)[-1]

    def pytest(self, *args, lines: int = 3) -> tuple[int, str]:
        rc, out, err = run([*self.cfg["pytest_cmd"], *args], self.repo, self.cfg, check=False, timeout=1800)
        return rc, gates.tail(out + err, lines)

    def suite(self, lines: int = 3) -> tuple[int, str]:
        """The full suite as CI runs it (06 §1a: gpu tests are the orchestrator's, not the suite's)."""
        return self.pytest("-m", "not gpu", lines=lines)

    def publish(self, step, branch: str, spec_file: str) -> None:
        """Push; open the PR on the first push. UI strings in app.py (06 §4) go into the body under
        'UI change — approve by seeing' and put label `ui-change` on the PR; neither stops the step."""
        self.push(branch)
        ui = gates.ui_strings(self.repo, self.base)
        body = (f"Loop step `{step.id}` (class {step.cls}, lane {step.lane}).\n\n"
                f"Spec: `{spec_file}`. Log: `loop/runs/{step.id}/log.md` on the PC.\n\n")
        if ui:
            body += ("## UI change — approve by seeing\n"
                     "This PR adds or changes UI strings in `app.py`. Nimrod approves by seeing after merge "
                     "(docs/06 §4).\n\n```text\n" + "\n".join(ui) + "\n```\n\n")
        body += "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
        if not self.pr_url:
            _, out, _ = gh(self.cfg, self.repo, "pr", "create", "--base", self.base, "--head", branch,
                           "--title", f"{step.id}: {step.title}", "--body", body)
            self.pr_url = out.strip().splitlines()[-1]
            self.log(step, f"PR {self.pr_url}")
        elif ui != self.ui:
            gh(self.cfg, self.repo, "pr", "edit", self.pr, "--body", body, check=False)
        if ui and ui != self.ui:
            self.label_ui(step, ui)
        self.ui = ui

    def label_ui(self, step, ui: list[str]) -> None:
        add = ("pr", "edit", self.pr, "--add-label", "ui-change")
        rc, _, err = gh(self.cfg, self.repo, *add, check=False)
        if rc != 0:  # label missing on the repo → create it, then add again
            gh(self.cfg, self.repo, "label", "create", "ui-change", "--color", "FBCA04",
               "--description", "UI strings changed: approve by seeing (docs/06 §4)", check=False)
            rc, _, err = gh(self.cfg, self.repo, *add, check=False)
        self.log(step, f"UI change: {len(ui)} line(s) in app.py · " +
                 ("labelled ui-change" if rc == 0 else f"label ui-change failed ({err.strip()[:120]})"))

    # -- sessions ------------------------------------------------------------------------
    def session(self, role: str, step, extra: dict, attempt: int = 1):
        self.check_budget()
        r = session.run_role(role, step, extra, self.cfg, self.repo, self.runs, attempt)
        self.log(step, f"{role} #{attempt} · {r.duration_s:.0f}s · {r.cost_usd:.2f} USD · "
                       f"{'ERROR ' + r.error if r.is_error else 'BLOCKED' if r.blocked else 'ok'}"
                       f"{'' if r.header_ok else ' · header missing (advisory)'}")
        where = f"\n\nFull reply: `loop/runs/{step.id}/{role}-{attempt}.json` on the PC."
        if r.is_error:
            raise Stop(f"{role} session error: {r.error}",
                       quoted("Reply (first 20 lines)", excerpt(r.text)) + where if r.text.strip() else "")
        if r.blocked:
            raise Stop(f"{role} blocked", quoted("Reply (first 20 lines)", excerpt(r.text)) + where)
        return r

    # -- the step ------------------------------------------------------------------------
    def preflight(self, step) -> None:
        if self.steps_started_today() >= self.cfg["steps_per_day"]:
            raise Stop(f"cap: steps_per_day ({self.cfg['steps_per_day']}) reached")
        self.check_budget()
        if git(self.repo, "branch", "--show-current").strip() != self.base or self.changed():
            raise Stop(f"repo not on a clean {self.base}")

    def run_step(self, step) -> None:
        self.pr_url, self.ui = None, []
        self.preflight(step)
        self.log(step, f"step start · {step.title} · class={step.cls} lane={step.lane} gpu={step.touches_gpu}")
        base_hash = git(self.repo, "rev-parse", "--short", "HEAD").strip()
        branch = f"loop/{step.id}"
        if git(self.repo, "branch", "--list", branch).strip():
            raise Stop(f"branch {branch} already exists (earlier run?)")

        # The Architect is read-only, so it runs on the base branch; a blocked spec leaves no branch.
        spec = self.session("architect", step, {}).text
        self.expect_changes(step, "architect", [])
        questions = blocking(spec)
        if questions:
            (self.runs / step.id / "spec-blocked.md").write_text(spec.rstrip() + "\n", encoding="utf-8")
            raise Stop("architect blocked", quoted("Blocking questions", questions) +
                       f"\n\nFull spec: `loop/runs/{step.id}/spec-blocked.md` on the PC.")
        git(self.repo, "checkout", "-q", "-b", branch)
        spec_file = f"steps/{step.id}/spec.md"
        (self.repo / spec_file).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / spec_file).write_text(spec.rstrip() + "\n", encoding="utf-8")
        self.commit([spec_file], "spec", step)

        tester = self.session("tester", step, {"spec": spec})
        tests = self.expect_changes(step, "tester", ["tests/"])
        pyfiles = [t for t in tests if t.endswith(".py") and (self.repo / t).exists()]
        if not pyfiles:
            raise Stop("tester wrote no test files", quoted("Reply (first 20 lines)", excerpt(tester.text)) +
                       f"\n\nFull reply: `loop/runs/{step.id}/tester-1.json` on the PC.")
        rc, tail = self.pytest(*pyfiles)
        self.log(step, f"tests on main + spec: exit {rc} · {tail.splitlines()[-1] if tail else ''}")
        if rc == 0:
            raise Stop("tests are not red on main (they pass before implementation)")
        if rc not in (1, 2):
            raise Stop(f"tests did not run (pytest exit {rc}): {tail}")
        self.commit(tests, "tests (red)", step)

        impl_paths = [p for p in step.paths if not within(p, ["tests/", "docs/", "steps/"])]
        defects, red = "", 0
        for attempt in range(1, self.cfg["attempts_per_step"] + 1):
            impl = self.session("implementer", step, {"spec": spec, "defects": defects}, attempt)
            changed = self.expect_changes(step, "implementer", impl_paths)
            if not changed:
                raise Stop("implementer made no change", quoted("Reply (first 20 lines)", excerpt(impl.text)) +
                           f"\n\nFull reply: `loop/runs/{step.id}/implementer-{attempt}.json` on the PC.")
            self.commit(changed, f"implementation (attempt {attempt})", step)
            rc, tail = self.suite(lines=60)
            if rc != 0:  # red before push: the tail is the next attempt's defect list; no CI, no review
                self.log(step, f"suite red after commit (exit {rc}) · {tail.splitlines()[-1] if tail else ''}")
                defects = ("The full suite (`pytest -q -m \"not gpu\"`) is red after your change. "
                           f"Last 60 lines:\n\n```text\n{tail}\n```")
                continue
            self.log(step, f"suite green after commit · {tail.splitlines()[-1] if tail else ''}")
            self.publish(step, branch, spec_file)
            ci = gates.ci_green(self.pr, self.cfg, self.repo)
            self.log(step, f"CI {'green' if ci else 'red/timeout'}")
            ci_log = "" if ci else gates.ci_failed_log(branch, self.cfg, self.repo, 60)
            diff = git(self.repo, "diff", f"{self.base}...HEAD")
            rev = self.session("reviewer", step, {"spec": spec, "diff": diff,
                                                  "ci": "green" if ci else "RED or timed out"}, attempt)
            approved, body = parse_verdict(rev.text, session.role_class("reviewer", step), step.id)
            self.log(step, "review APPROVE" if approved else f"review red: {body.splitlines()[0][:120]}")
            if approved and ci:
                break
            red = 0 if approved else red + 1
            if red >= self.cfg["consecutive_red_reviews_stop"]:
                raise Stop(f"{red} consecutive red reviews")
            defects = (body if not approved else "") + ("" if ci else
                "\n\nCI is red on the PR. Last 60 lines of `gh run view --log-failed` for the latest run on "
                f"`{branch}`:\n\n```text\n{ci_log}\n```")
        else:
            raise Stop(f"{self.cfg['attempts_per_step']} implementer attempts without APPROVE + green CI")

        if step.touches_gpu:
            try:                        # gpu_test waits for an idle ComfyUI before each run
                ok, n, tail, runs = gates.gpu_test(self.cfg, self.repo, step.gpu_env)
            except gates.ComfyBusy as e:
                raise Stop(f"ComfyUI busy for {self.cfg['comfy_wait_s']}s; GPU test not run ({e})")
            self.log(step, "GPU test " + " · ".join(f"{r['label']} {r['n']}/4" for r in runs)
                     + f" · {'pass' if ok else 'FAIL'}")
            if not ok:
                raise Stop(f"real-generation test {n}/4 (< {self.cfg['gpu_min_pass']}/4):\n{tail}")

        hits = gates.touched_never_economize(self.cfg, self.repo, self.base)
        why = merge_refusal(step, hits, self.cfg)
        if why:
            _, _, err = gh(self.cfg, self.repo, "pr", "edit", self.pr, "--add-label", "needs-nimrod", check=False)
            raise Stop(f"needs-nimrod: PR-ready, not auto-merged ({why})")
        if hits:
            self.log(step, "never-economize lane open · hits named in the spec: " + ", ".join(hits))

        # 04 queue flip + STATE ride on the PR branch (ruling 10a), then CI again, then merge.
        queue.mark_done(step.id, self.pr_url, self.repo / PLAN)
        nxt = queue.next_step(self.repo / PLAN)
        (self.repo / "docs" / "STATE.md").write_text(
            f"Main at {base_hash} + {step.id} ({self.pr_url}) · phase {self.cfg.get('phase', '?')} · "
            f"last merged {step.id} · next {nxt.id if nxt else 'queue empty'} · carried {self.carried()}\n",
            encoding="utf-8")
        self.commit([PLAN.as_posix(), "docs/STATE.md"], "queue + state", step)
        self.push(branch)
        if not gates.ci_green(self.pr, self.cfg, self.repo):
            raise Stop("CI red after the queue/state commit")
        gh(self.cfg, self.repo, "pr", "merge", self.pr, "--squash", "--delete-branch")
        git(self.repo, "checkout", "-q", self.base)
        git(self.repo, "pull", "-q", "--ff-only", "origin", self.base)
        rc, tail = self.suite()
        if rc != 0:
            raise Stop(f"suite red on {self.base} after merge: {tail}")
        self.log(step, f"merged {self.pr_url} · suite on {self.base}: {tail.splitlines()[-1] if tail else 'ok'}")

    def carried(self) -> str:
        _, out, _ = gh(self.cfg, self.repo, "issue", "list", "--state", "open", "--search",
                       '"loop: needs-nimrod" in:title', "--json", "title", check=False)
        try:
            titles = [i["title"].rsplit(" ", 1)[-1] for i in json.loads(out or "[]")]
        except (ValueError, KeyError, TypeError):
            return "unknown"
        return ", ".join(titles) or "none"

    def stop(self, step, reason: str, detail: str = "") -> None:
        """State line to the log, then open or append issue `loop: needs-nimrod <id>`."""
        self.log(step, f"STOP · {reason}")
        title = f"loop: needs-nimrod {step.id}"
        body = (f"Step `{step.id}` — {step.title} — stopped.\n\n**Reason:** {reason}\n\n"
                + (f"{detail}\n\n" if detail else "") +
                f"PR: {self.pr_url or 'none'} · log: `loop/runs/{step.id}/log.md` on the PC.")
        try:
            _, out, _ = gh(self.cfg, self.repo, "issue", "list", "--state", "open", "--search",
                           f'"{title}" in:title', "--json", "number,title", check=False)
            same = [i for i in json.loads(out or "[]") if i.get("title") == title]
            if same:
                gh(self.cfg, self.repo, "issue", "comment", str(same[0]["number"]), "--body", body)
                self.log(step, f"issue #{same[0]['number']} appended")
                return
            rc, out, err = gh(self.cfg, self.repo, "issue", "create", "--title", title, "--body", body,
                              "--label", "needs-nimrod", check=False)
            if rc != 0:  # label missing (06 §9 setup) → open it unlabelled and say so
                self.log(step, f"issue with label failed ({err.strip()[:120]}); retrying without label")
                _, out, _ = gh(self.cfg, self.repo, "issue", "create", "--title", title, "--body", body)
            self.log(step, f"issue {out.strip()}")
        except Exception as e:  # the stop itself must not crash the loop's exit path
            self.log(step, f"could not open issue: {e}")


def run_loop(cfg: dict, repo, runs_dir, once: bool = False) -> int:
    """0 = merged (or queue empty); 1 = stopped for Nimrod."""
    d = Driver(cfg, repo, runs_dir)
    while True:
        step = queue.next_step(Path(repo) / PLAN)
        if step is None:
            print("queue empty")
            return 0
        try:
            d.run_step(step)
        except Stop as e:
            d.stop(step, str(e), e.detail)
            return 1
        except Exception as e:
            d.stop(step, f"error: {type(e).__name__}: {e}")
            return 1
        if once:
            return 0


def dry_run(cfg: dict, once: bool) -> int:
    """Run on a temp clone of the current HEAD (as `main`) whose origin is a temp bare repo, with
    fake claude, fake gh and a stub GPU test. Nothing leaves the machine; logs land in
    loop/runs/_dryrun/<stamp>/."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    runs_dir = LOOP / "runs" / "_dryrun" / stamp
    runs_dir.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="loop-dryrun-"))
    bare, work = tmp / "origin.git", tmp / "work"
    head = git(ROOT, "rev-parse", "HEAD").strip()
    run(["git", "clone", "-q", "--bare", str(ROOT), str(bare)], tmp)
    git(bare, "update-ref", "refs/heads/main", head)
    run(["git", "clone", "-q", "--branch", "main", str(bare), str(work)], tmp)
    origin = git(work, "remote", "get-url", "origin").strip()
    if Path(origin).resolve() != bare.resolve():
        raise SystemExit(f"dry-run refused: clone origin is {origin}, not the temp bare repo")
    os.environ.setdefault("FAKE_CLAUDE_LOG", str(runs_dir / "claude-calls.jsonl"))
    os.environ.setdefault("FAKE_GH_LOG", str(runs_dir / "gh-calls.jsonl"))
    py = sys.executable
    cfg = dict(cfg,
               claude_cmd=os.environ.get("LOOP_CLAUDE_CMD") or [py, str(LOOP / "fake_claude.py")],
               gh_cmd=os.environ.get("LOOP_GH_CMD") or [py, str(LOOP / "fake_gh.py")],
               pytest_cmd=[py, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
               gpu_cmd=[py, "-c", "print('4/4 passed. (dry-run stub for local/run_batch.py)')"],
               ci_poll_s=1, comfy_wait_s=min(cfg["comfy_wait_s"], 60))
    print(f"dry-run: HEAD {head[:7]} as main · clone {work} · origin {bare} · logs {runs_dir}")
    rc = run_loop(cfg, work, runs_dir, once)
    print(f"dry-run: exit {rc}")
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="temp clone, fake claude/gh, no remote writes")
    ap.add_argument("--once", action="store_true", help="run at most one step")
    a = ap.parse_args(argv)
    cfg = config.load_config()
    if a.dry_run:
        return dry_run(cfg, a.once)
    return run_loop(cfg, ROOT, LOOP / "runs", a.once)


if __name__ == "__main__":
    sys.exit(main())
