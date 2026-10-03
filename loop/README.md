# loop/ — the build-loop orchestrator (docs/06_Loop_Spec.md)

## Run (on the PC, from `E:\qr-art-forge`, on a clean `main`)
```
.venv\Scripts\python.exe loop\run.py --dry-run --once   # temp clone, fake claude + gh, no remote writes
.venv\Scripts\python.exe loop\run.py --once             # one real step from the docs/04 ## Queue
.venv\Scripts\python.exe loop\run.py                    # steps until the queue is empty or a cap stops it
```
Exit 0 means a step merged or the queue is empty. Exit 1 means the loop stopped; the reason is in the log and in issue `loop: needs-nimrod <id>`.
Before the first real run, 06 §9 setup must be done: `gh auth`, the `needs-nimrod` label (issues open unlabelled until it exists), and `claude` logged in.

## Flow per step
Architect (spec) → Tester (tests must be red on main) → [Implementer → commit → full suite → push/PR → CI → Reviewer] × 2 → GPU test if `touches_gpu=yes` (after ComfyUI is idle) → merge only if `lane=ordinary`, APPROVE, CI green and no never-economize path is touched.
- Suite after commit: `pytest -q -m "not gpu"` runs after each implementation commit, before any push. Red → its last 60 lines are the next attempt's defects; no push, no CI wait, no Reviewer that attempt.
- CI red → the last 60 lines of `gh run view <latest run on the branch> --log-failed` go into the next attempt's defects (with the Reviewer's, if any).
- An Implementer that changes nothing stops the step (`implementer made no change`); no push, no review. A Tester that writes no test file stops it too; both issues carry the reply excerpt.
- UI flag: added or changed `app.py` lines containing `label=`, `placeholder=` or `gr.Markdown(` are listed in the PR body under "UI change — approve by seeing", and the PR gets label `ui-change` (created if missing). Neither stops the step or affects auto-merge.
If it merges: the queue flip + `docs/STATE.md` are committed on the PR branch, CI runs again, then squash-merge and `pytest` on main.
If it doesn't: the PR is labelled `needs-nimrod` and the loop stops.
A role may stop and report instead (06 §1): its reply starts with `BLOCKED: <reason>` (after the header, if given). The Architect blocks by writing anything other than `None` under "Blocking questions" (or a `Status: BLOCKED` line). The Architect runs on `main`, so a blocked spec leaves no branch behind. The spec is saved to `runs/<id>/spec-blocked.md`, and the loop stops before the Tester. Every stop's issue carries the reason plus the blocking text or the first 20 lines of the reply (session errors too).
The driver commits, pushes and calls `gh`; sessions never do. After each session it checks `git status` against the role's paths (Architect/Reviewer: none; Tester: `tests/`; Implementer: the step's paths minus `tests/`, `docs/`, `steps/`).

## Sessions: prompt on stdin
`claude -p --output-format json --max-turns 40 --model <pinned id> --permission-mode dontAsk --tools <set> --allowedTools <set> [--disallowedTools <git push/commit/…, gh>]`, with the prompt from `prompts/<role>.md` **on stdin**.
- Stdin because Windows caps a command line at 32,767 chars and the Reviewer prompt carries the full diff.
- `--tools` limits which tools exist, `--allowedTools` pre-approves them, and `dontAsk` denies the rest.
- Bash is limited to pytest and read-only git; `python` only as `python -m pytest`.
- `--max-turns` works but is hidden from `claude --help` (2.1.283).
- Each session's model is checked from the JSON `modelUsage`: the pinned id for the role's class must be there (helpers such as haiku may appear beside it), else the step stops with `wrong model`. The header line is advisory: a missing one is logged as `header missing (advisory)` and the reply is read as if line 1 were absent.

## GPU test, secrets, the gate (M2.10)
- **gpu_env**: a queue line may end its fields with ` · gpu_env=K=V[;K2=V2]` (before any PR URL). The GPU test then runs twice — once with the normal env, once with those variables added — and passes only if both reach `gpu_min_pass`. ComfyUI must be idle (within `comfy_wait_s`) before each run, else the step stops. The log line reads `GPU test default n/4 · with gpu_env n/4 · pass|FAIL`; a stop carries the failing run's tail.
- **Stripped env**: child processes (sessions, pytest, git, gh) never see `HF_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`, `REJECTS_REPO` (`sh.SECRETS`, case-blind). Only the GPU test keeps them, because `run_batch.py` may archive rejects. `gh` and `git push` must therefore authenticate from their own stored login.
- **Gate in app.py** (`[never_economize]`): on `git show <base>:app.py`, the whole of each `gate_functions` def (`run_forge`, `forge`, decorators included) and every `from validator import` / `import validator` line are gate spans. A hunk overlapping a span, a changed line containing a `gate_marker` (`THE GATE`, `DISCLOSURE`), or a hunk within `gate_context` (3) lines of a marker line flags `app.py (gate)`. So does any added or removed line, anywhere in app.py, containing the token `validate` (`\bvalidate\b`; catches a module-level rebinding outside the spans). If base's app.py does not parse, or defines none of the gate functions, any app.py change is flagged (fail closed) and the label says why.

## Caps (`config.toml`)
3 steps/day · 2 implementer attempts/step · 40 turns/session · 40 USD/day (sum of `total_cost_usd` in today's run JSONs) · stop on 2 consecutive red reviews · ComfyUI wait 600 s · CI wait 1200 s. Any cap hit stops the loop and opens an issue.

## Logs
`loop/runs/<id>/log.md` gets one line per stage. `loop/runs/<id>/<role>-<attempt>.json` holds the prompt, argv, raw JSON and cost. Dry-runs log to `loop/runs/_dryrun/<stamp>/`. `runs/` is git-ignored.
`LOOP_CLAUDE_CMD` and `LOOP_GH_CMD` override the commands; tests use `fake_claude.py` and `fake_gh.py`.

## Calibration seeds
`seeds/<n>-<slug>.json` is one exact edit `{"file", "old", "new", "defect"}` (or a list of them, for seed 3, which spans two requirements files). `calibrate.py` replaces `old` with `new`; `old` must occur exactly once in the file on the base, else it is an error. `tests/test_calibrate.py` checks every `old` against HEAD. Small snippets keep unrelated steps from breaking a seed (a `.patch` breaks on any change in its diff context, as in the m2-6 pilot); a step that changes the seeded snippet itself still turns the suite red.
Seeds 1–8 are **listed** (06 §6 names them); 9–11 are **controls** (not on that list: tilt condition dropped, pass rule off by one, quiet zone 2). Before each seed, a prep commit in the worktree replaces the §6 list in `docs/06_Loop_Spec.md` with `(withheld during calibration)` and removes `loop/seeds/` and `docs/07_Calibration.md`; the seed is a second commit, and the Reviewer's diff is `<prep>...HEAD` — exactly the seed — on a clean worktree with no defect list to read. `summary.md` marks each seed's kind. Exit 0 iff every listed seed is caught and ≥ 2 of 3 controls are.
