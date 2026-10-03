# 06 — Loop Spec v0.5 (2026-10-03)

The automated build loop for QR Art Forge. Runs on Nimrod's Windows PC (RTX 4070) in `E:\qr-art-forge`, on his Claude subscription, via `claude -p`; the Mac is courier only. GitHub for PRs and CI. Nothing here overrides 00–05; where they conflict, 00–05 win.

## 1. Shape

One **step** = one queue item from `docs/04` (or an Open Discussion entry promoted to a step). A step passes through five fresh sessions, none sharing context:

| Role | Model class | Input | Output | Writes to |
|---|---|---|---|---|
| Architect | top | docs/00–05, step title | `steps/<id>/spec.md` (scope, behaviour table, editable paths, class) | nothing (driver saves the reply as `steps/<id>/spec.md`) |
| Tester | top | spec | tests, which must FAIL on main; plus the real-generation test (§1a) when the step touches `app.py`, `qrbuild.py` or `validator.py` | `tests/` only |
| Implementer | per class in spec | spec + failing tests | code; never touches `tests/`, `docs/`, `steps/` | editable paths in spec |
| Reviewer | top | spec + `git diff main` | `approve` or numbered defects | nothing |
| Merger | none (script) | reviewer verdict + CI | squash-merge, delete branch, rerun suite on main, state line | main |

A role may stop and report instead of doing its task. Its final message then starts with `BLOCKED: <reason>` (after the header, if given). The driver stops the step and puts the reply in the needs-nimrod issue. The Architect blocks by writing a non-empty 'Blocking questions' section; the driver stops before the Tester.

The driver verifies each session's model from the JSON `modelUsage`; the header line is advisory.

### 1a. Real-generation test
`local\run_batch.py --seed 12345` (peony, defaults) must report ≥ 2/4 pass. When the queue line carries `gpu_env=…`, the driver runs it a second time with that environment and both runs must pass. Runs on the PC only; no real-generation test lives in `tests/` (only the marker stand-in `test_markers.py::test_dummy_gpu` is GPU-marked). Before each GPU run the driver checks ComfyUI's queue; busy past `comfy_wait_s` is a stop, not a retry.

Defects go back to a **new** Implementer session with the defect list appended. Max 2 implementer attempts per step; then the step stops PR-ready with `needs-nimrod`. Suite after commit; red → defects, no push.

Sessions run with `--output-format json --max-turns <cap> --model <class> --allowedTools` limited to the role (Reviewer: read-only tools; Tester/Implementer: read, edit, bash for `pytest` and `git`). No session runs `git push`, `gh pr merge`, or anything touching Space secrets; the orchestrator does those.

## 2. Task classes → models (dated 2026-09-24)

| Class | Model | Used for |
|---|---|---|
| top | Opus 5.5 | spec, tests, review, ADRs, never-economize code |
| long-pass | Opus 5.5 | multi-file implementation (M3 backend) |
| scoped | Sonnet 5 | UI, plumbing, single-module changes |
| cheap | Haiku 4.5 | none in v1 |

Unavailability rule (from 00): ordinary work may move one class up or down and the move is recorded in the handover; never-economize work is held.

## 3. Lanes

- **Ordinary** (not on the never-economize list): merges automatically on `approve` + CI green.
- **Never-economize** (`validator.py`, `qrbuild.py`, `README.md` front-matter, `.github/`, the gallery gate in `app.py`): stops at PR-ready with label `needs-nimrod` until §6 calibration is met; thereafter merges automatically.

The Architect names the lane in the spec; the orchestrator refuses to auto-merge if the diff touches a never-economize path, any hunk inside `run_forge()`/`forge()`, the validator import, or any changed line mentioning `validate` or a gate marker in `app.py`, whether or not the spec named it. (`README.md` is protected whole, stricter than "front-matter".)

## 4. Where Nimrod is

- **Decisions inbox**: GitHub issues labelled `needs-nimrod`, body = options + recommendation, answerable in one word. Anything touching `docs/02`, secrets, or persisted data blocks the step; UI wording proceeds on a default and is flagged in the PR body.
- **Approve by seeing**: any PR touching UI strings is flagged in its body and labelled `ui-change`; Nimrod approves by seeing after merge. Screenshots: OD 11.
- **Approve by using**: milestone gates only (phone scan). Steps inside a milestone don't wait for it.
- **Always Nimrod's**: money, accounts, secrets, naming, legal/UI disclosure text, destructive actions on real data, the Space's hardware.

## 5. Guards

- Caps: 3 steps/day, 2 implementer attempts/step, `--max-turns 40` per session, daily spend ceiling read from session JSON `total_cost_usd` (USD 40 equivalent (Nimrod, 2026-09-29); subscription usage counts the same way). Any cap hit → loop pauses, state line posted as an issue.
- Stop on **two consecutive red reviews** on the same step.
- Pinned versions: sessions run in the repo's `.venv` from `requirements-ci.txt`; CI uses the same file.
- Provenance: any `docs/` change must cite `file:line` or a quoted decision of Nimrod's (issue/PR comment URL); the Reviewer rejects otherwise.
- No secrets in git. Sessions, pytest and `sh.run` get `HF_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, `ANTHROPIC_API_KEY` and `REJECTS_REPO` stripped; only the GPU test process keeps them. `gh` and `git push` run on their on-disk auth. Residual (accepted until M3): gh's on-disk auth is readable by test code the driver runs.
- The header line is advisory; the orchestrator verifies the model from `modelUsage` (§1).

## 6. Reviewer calibration (before never-economize auto-merge)

Replay the eight real defects (seven from Phase B, one from M2.1) as seeded edits on a scratch worktree, one at a time, with this list, `docs/07` and `loop/seeds/` withheld from the Reviewer, plus three unlisted control seeds (`loop/seeds/9–11`); the Reviewer must reject all eight and at least two controls, in one full run:
1. unpinned `huggingface_hub` (M0) · 2. README `short_description` > 60 (M1.1) · 3. gradio/pydantic incompatibility (M1.2) · 4. `sdk_version` ≠ requirements pin (M1.2) · 5. starlette/gradio 4 mismatch (M1.3) · 6. DreamShaper scheduler `deis` config (M1.4) · 7. a validator that gates on OpenCV (M1.6/1.8 lesson) · 8. a gallery that re-encodes validated pixels (M2.1) — a contract gap found by reading, not by a failing test.
Plus mutation testing on `validator.py` and `qrbuild.py`: ≥ 90 % of non-equivalent mutants killed; every survivor triaged in 07 as equivalent or a named test gap, and every gap closed before the lane opens. Run as a plain script, runner limited to `tests/test_validator.py tests/test_qrbuild.py`. Report filed as `docs/07_Calibration.md`; Nimrod says yes/no.

## 7. Pilot

Step: **m2-6 negative prompt field** — ordinary lane, scoped class, no contract change. Success: loop runs Architect→Merger without Nimrod. (Changed 2026-09-29 from the bleed canvas, which needs a 02 change: Nimrod on issue #15, 'C, a'.)

## 8. State line

After every merge the orchestrator writes `docs/STATE.md`: `Main at <hash> · phase · last merged · next · carried`. A new planner chat starts from it.

## 9. Build order (Phase C)

1. This spec approved → 2. one-time setup (Nimrod: `claude` login on the PC, `gh auth`, label `needs-nimrod`, `HF_TOKEN` in shell env) → 3. `loop/` orchestrator (Python, ~300 lines) + CI hook, built as an ordinary manual step → 4. calibration → 5. pilot → 6. never-economize lane opens.

## Changes
- v0.1 (2026-09-24) — initial draft.
- v0.2 (2026-09-26) — host = Windows PC; real-generation test; ComfyUI-idle guard; calibration defect 8. Approved by Nimrod in chat 2026-09-26.
- v0.3 (2026-09-29) — pilot = m2-6; BLOCKED handling (§1). Provenance: issue #15.
- v0.3.1 (2026-09-29) — model verified from modelUsage; header advisory; 40 USD. Provenance: loop runs m2-5 tester-1 and m2-6 implementer-1 (good sessions stopped on header).
- v0.4 (2026-09-29) — suite after commit; CI log to Implementer; no-change stop; UI flag; seeds as exact edits. Provenance: loop run m2-6, PR #19.
- v0.5 (2026-10-03) — gpu_env + double GPU run; secrets stripped from sessions and pytest; gate = run_forge/forge spans + validate token; unprimed calibration with control seeds 9–11; mutation bar on non-equivalent mutants. Provenance: planner audit F2–F4, chat 2026-10-03; PR #21.
