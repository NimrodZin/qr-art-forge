# 06 — Loop Spec v0.2 (2026-09-26)

The automated build loop for QR Art Forge. Runs on Nimrod's Windows PC (RTX 4070) in `E:\qr-art-forge`, on his Claude subscription, via `claude -p`; the Mac is courier only. GitHub for PRs and CI. Nothing here overrides 00–05; where they conflict, 00–05 win.

## 1. Shape

One **step** = one queue item from `docs/04` (or an Open Discussion entry promoted to a step). A step passes through five fresh sessions, none sharing context:

| Role | Model class | Input | Output | Writes to |
|---|---|---|---|---|
| Architect | top | docs/00–05, step title | `steps/<id>/spec.md` (scope, behaviour table, editable paths, class) | `steps/` only |
| Tester | top | spec | tests, which must FAIL on main; plus the real-generation test (§1a) when the step touches `app.py`, `qrbuild.py` or `validator.py` | `tests/` only |
| Implementer | per class in spec | spec + failing tests | code; never touches `tests/`, `docs/`, `steps/` | editable paths in spec |
| Reviewer | top | spec + `git diff main` | `approve` or numbered defects | nothing |
| Merger | none (script) | reviewer verdict + CI | squash-merge, delete branch, rerun suite on main, state line | main |

### 1a. Real-generation test
`local\run_batch.py --seed 12345` (peony, defaults) must report ≥ 50 % pass. Runs on the PC only; marked `@pytest.mark.gpu` and skipped in CI. Before any GPU test the session checks `local\comfy_state.py`; if ComfyUI is busy it waits, and VRAM contention is a stop, not a retry.

Defects go back to a **new** Implementer session with the defect list appended. Max 2 implementer attempts per step; then the step stops PR-ready with `needs-nimrod`.

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

The Architect names the lane in the spec; the orchestrator refuses to auto-merge if the diff touches a never-economize path the spec did not name.

## 4. Where Nimrod is

- **Decisions inbox**: GitHub issues labelled `needs-nimrod`, body = options + recommendation, answerable in one word. Anything touching `docs/02`, secrets, or persisted data blocks the step; UI wording proceeds on a default and is flagged in the PR body.
- **Approve by seeing**: any PR touching `build_ui` attaches a screenshot of the Space (orchestrator renders the Gradio app locally and captures it).
- **Approve by using**: milestone gates only (phone scan). Steps inside a milestone don't wait for it.
- **Always Nimrod's**: money, accounts, secrets, naming, legal/UI disclosure text, destructive actions on real data, the Space's hardware.

## 5. Guards

- Caps: 3 steps/day, 2 implementer attempts/step, `--max-turns 40` per session, daily spend ceiling read from session JSON `total_cost_usd` (proposed USD 15 equivalent; subscription usage counts the same way). Any cap hit → loop pauses, state line posted as an issue.
- Stop on **two consecutive red reviews** on the same step.
- Pinned versions: sessions run in the repo's `.venv` from `requirements-ci.txt`; CI uses the same file.
- Provenance: any `docs/` change must cite `file:line` or a quoted decision of Nimrod's (issue/PR comment URL); the Reviewer rejects otherwise.
- No secrets in git; the orchestrator holds `HF_TOKEN` only in the shell environment.
- Every session begins with its task class and step id on line one (CLAUDE.md rule); the orchestrator checks it.

## 6. Reviewer calibration (before never-economize auto-merge)

Replay the seven real Phase B defects as seeded bugs on a scratch branch, one at a time; the Reviewer must reject all seven:
1. unpinned `huggingface_hub` (M0) · 2. README `short_description` > 60 (M1.1) · 3. gradio/pydantic incompatibility (M1.2) · 4. `sdk_version` ≠ requirements pin (M1.2) · 5. starlette/gradio 4 mismatch (M1.3) · 6. DreamShaper scheduler `deis` config (M1.4) · 7. a validator that gates on OpenCV (M1.6/1.8 lesson) · 8. a gallery that re-encodes validated pixels (M2.1) — a contract gap found by reading, not by a failing test.
Plus mutation testing on `validator.py` and `qrbuild.py`: ≥ 90 % of mutants killed by the suite. Report filed as `docs/07_Calibration.md`; Nimrod says yes/no.

## 7. Pilot

Step: **OD #6 (1) bleed canvas** — 768×1024 control image, code centred, model paints freely beyond it; ordinary lane; scoped class. Success: loop runs Architect→Merger without Nimrod; PR carries a screenshot; the M2 gate (phone) follows.

## 8. State line

After every merge the orchestrator writes `docs/STATE.md`: `Main at <hash> · phase · last merged · next · carried`. A new planner chat starts from it.

## 9. Build order (Phase C)

1. This spec approved → 2. one-time setup (Nimrod: `claude` login on the Mac, `gh auth`, label `needs-nimrod`, `HF_TOKEN` in shell env) → 3. `loop/` orchestrator (Python, ~300 lines) + CI hook, built as an ordinary manual step → 4. calibration → 5. pilot → 6. never-economize lane opens.

## Changes
- v0.1 (2026-09-24) — initial draft.
- v0.2 (2026-09-26) — host = Windows PC; real-generation test; ComfyUI-idle guard; calibration defect 8. Approved by Nimrod in chat 2026-09-26.
