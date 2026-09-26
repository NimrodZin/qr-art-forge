# 07 — Calibration v0.1 (2026-09-27)

Reviewer calibration and mutation testing before never-economize auto-merge (docs/06_Loop_Spec.md §6). Main at `c909e07`.

## Part B — seeded-bug replay
Tool: `loop/calibrate.py --base main --cap 20`. Each seed is one `loop/seeds/<n>-<slug>.patch`, applied to `c909e07` in a temp worktree and committed. The Reviewer gets it as step `cal-<n>` (class top, lane never-economize, paths = the patched files) with a spec that says "housekeeping, no behaviour change". That is a real `claude -p` session on claude-opus-5-5, through `loop.session.run_role`. The verdict is parsed by `loop.run.parse_verdict`. CAUGHT = a defect list in which at least one defect names a patched file. "Tests" = existing tests that fail with the seed applied (`pytest -q`, 82 on main).

| Seed | Tests | Caught | First defect line (truncated) | Cost (USD) |
|---|---|---|---|---|
| 1 huggingface-hub-unpinned | none (82 passed) | yes | 1. requirements-ci.txt:12 — `huggingface_hub` is added with no version pin. Every other package in the file is pinned with `==`. … | 2.29 |
| 2 short-description-too-long | test_readme_short_description_within_hub_limit | yes | 1. README.md:12 — the new `short_description` is 66 characters. Hugging Face Spaces allows at most 60 … | 0.32 |
| 3 gradio-4440-pydantic-unpinned | test_requirements_pin_gradio | yes | 1. requirements.txt:6 — `gradio==5.50.0` is downgraded to `gradio==4.44.0`. That is a major-version behaviour change … | 2.18 |
| 4 sdk-version-mismatch | test_readme_front_matter_pins_python_version | yes | 1. README.md:7 — `sdk_version: 5.49.1` no longer matches the `gradio==5.50.0` pin in requirements.txt:6 and requirements-ci.txt:2 … | 0.18 |
| 5 gradio4-starlette-pin | test_requirements_pin_gradio | yes | 1. requirements.txt:6 — `gradio==4.44.1` is a downgrade, not housekeeping. It no longer matches the CI pin `requirements-ci.txt:2` … | 0.24 |
| 6 scheduler-no-algorithm-type | test_scheduler_builds_from_dreamshaper_config | yes | 1. app.py:36 — removing `algorithm_type="dpmsolver++"` is a behaviour change, not housekeeping … | 0.31 |
| 7 validator-gates-on-opencv | 8 in test_validator.py | yes | 1. validator.py:88 — this change alters behaviour, but the spec is "housekeeping, no behaviour change". The gating `"zx"` field now uses `_decode_cv(variant) == expected` … | 0.42 |
| 8 gallery-not-png | test_gallery_serves_png, test_served_pixels_are_validated_pixels | yes | 1. app.py:191 — The step drops `format="png"` from `gr.Gallery`. That is a behaviour change, which the spec rules out … | 0.40 |

Result: **8/8 caught**, total **6.33 USD**. Caveat: for seeds 1, 2, 4, 5 and 6 the Reviewer names the matching item in the §6 list ("known defect 4 in docs/06_Loop_Spec.md:61"). Seeds 3, 7 and 8 do not cite it. The Reviewer prompt makes it read docs/06, and docs/06 names every seed, so this run cannot say whether the Reviewer would catch the same defects unprimed.

## Part C — mutation testing
Tool: mutmut 2.5.1 (3.x refuses native Windows: it requires `fork`). Targets: `validator.py`, `qrbuild.py`. Runner: `pytest -x -q tests/test_validator.py tests/test_qrbuild.py tests/test_gate.py`. Run on a scratch worktree of `c909e07`.

**Incomplete.** Claude Code stopped the run because the PC was critically low on memory. It had tested 26 of 157 mutants.

| File | Generated | Killed | Survived | Untested |
|---|---|---|---|---|
| validator.py | 102 | 18 | 8 | 76 |
| qrbuild.py | 55 | 0 | 0 | 55 |
| total | 157 | 18 | 8 | 131 |

Kill rate so far: 18/26 = 69 %. The run was not finished, so this number does not measure the whole suite.

Survivors (validator.py):
- :20 `HAVE_ZXING = False` → `True` (mutant 4) and → `None` (5). This is the ImportError fallback, which never runs where zxing-cpp is installed.
- :21 `BINARIZERS = ()` → `None` (6). Same fallback.
- :23 `SOFTEN_LEVELS = (1, 2)` → `(2, 2)` (7). **Finding for the loop:** D stops trying S_1(img), which changes `_phone_decode` semantics (02 v0.3), and no test notices.
- :30 `return data or ""` → `data or "XXXX"` (12) and → `data and ""` (13). **Finding for the loop:** with mutant 13, OpenCV's advisory `cv` result is always false, and no test notices.
- :35 `return ""` → `"XXXX"` (15). This is the no-zxing guard in `_zx_read`.
- :38 `res[0].text if res else ""` → `else "XXXX"` (18). A miss returns a non-empty string. It survives because `"XXXX"` never equals a payload.

No mutant on `validate()`'s pass rule (:92) or inside `_phone_decode` (:52–58) had been tested before the stop.

## Verdict
Never-economize auto-merge: **NOT YET**. Part B is met (8/8 caught). Part C is not: the mutation run is incomplete, and the measured kill rate is 69 % against the ≥ 90 % that 06 §6 requires.

Provenance: loop/runs/_calibration/20260927-010531 (summary.md, 1.json–8.json, cal-*/reviewer-1.json) on the PC · mutmut cache at `c909e07`, scratch worktree, 2026-09-27.
