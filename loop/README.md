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
Architect (spec) → Tester (tests must be red on main) → [Implementer → push/PR → CI → Reviewer] × 2 → GPU test if `touches_gpu=yes` (after ComfyUI is idle) → merge only if `lane=ordinary`, APPROVE, CI green and no never-economize path is touched.
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

## Caps (`config.toml`)
3 steps/day · 2 implementer attempts/step · 40 turns/session · 40 USD/day (sum of `total_cost_usd` in today's run JSONs) · stop on 2 consecutive red reviews · ComfyUI wait 600 s · CI wait 1200 s. Any cap hit stops the loop and opens an issue.

## Logs
`loop/runs/<id>/log.md` gets one line per stage. `loop/runs/<id>/<role>-<attempt>.json` holds the prompt, argv, raw JSON and cost. Dry-runs log to `loop/runs/_dryrun/<stamp>/`. `runs/` is git-ignored.
`LOOP_CLAUDE_CMD` and `LOOP_GH_CMD` override the commands; tests use `fake_claude.py` and `fake_gh.py`.
