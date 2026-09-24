# CLAUDE.md — QR Art Forge

Read `docs/00_Project_Instructions.md` through `docs/05_Open_Discussion.md`, in order, before anything else. They outrank this file and general knowledge.

**Name your task class at the start of every session** (top / long-pass / scoped / cheap) and the step you are on. Stop if your model is below the class the prompt names.

## Terminology
payload — the exact string encoded · control image — the grey-canvas QR fed to ControlNet · candidate — a generated image · survivor — a candidate with `validate()["pass"] == True` · rescue — the single img2img retry · gate — Nimrod's real-phone scan.

## Layout
- `app.py` — Gradio UI and `forge()`; models load lazily.
- `qrbuild.py` — payload normalisation and control image. NEVER ECONOMIZE.
- `validator.py` — pass/fail contract. NEVER ECONOMIZE.
- `tests/` — pytest; CPU only; generation is mocked.
- `docs/` — the contract.
- `README.md` — Space front-matter (deploy config). NEVER ECONOMIZE.

## Read-only for implementers
`docs/`, `tests/`, `validator.py` semantics. An implementer that needs a change there stops and reports.

## How a step ends
`pytest -q` totals (which tests were red before, green after), files changed, a **Not certain** section ("None" written out), and a deploy-status line: `Deploy: <none | Space rebuild pending | Space live at <url>>`. Never merge, push to main, or touch Space secrets.

## Unavailability rule
If the assigned model is unavailable: ordinary work may move one class up or down and is recorded in the handover; never-economize work is held or drafted for the assigned model's later review — never reassigned, never self-reviewed.

## Guards
No secrets in git. Pinned versions in `requirements.txt` match CI for packages present in both files; `torch` and `huggingface_hub` are supplied by the Space image and stay unpinned there (decided M1.2/M1.4). Stop conditions are "stop and report", never "fix it". "Not found" is acceptable; a guess is not.
