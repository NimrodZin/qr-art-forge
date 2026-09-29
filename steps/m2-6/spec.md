Class: top · Step: m2-6

# m2-6 — Negative prompt field under Advanced (OD 9)

Source: docs/05_Open_Discussion.md:13 — "**Negative prompt field** under Advanced, appended to the fixed default. Nimrod 2026-09-26." Queue entry: docs/04_Build_Plan.md:31. Pilot step per docs/06_Loop_Spec.md:68-70.

## 1. Scope

### What changes (app.py only)
1. **New pure helper `build_negative(extra: str | None) -> str`** at module level in `app.py`.
   - If `extra` is `None`, or is empty or whitespace-only after `.strip()`, it returns `NEG` unchanged.
   - Otherwise it returns `NEG + ", " + extra.strip()`.
   - It does no other processing: no deduplication, no lower-casing, no length cap, no stripping of commas or newlines inside the text.
2. **`NEG` stays the same.** The constant at `app.py:18-19` keeps its exact current value. It is still the fixed default, and the user text is appended to it (OD 9, "appended to the fixed default").
3. **`run_forge` gets a keyword parameter `negative: str = ""`.** The current signature is at `app.py:119-121`.
   - The new parameter goes after `progress`, so every existing positional call keeps working. That covers the 8-positional + `pipes=` calls in `tests/test_gate.py:26` and `tests/test_rejects.py:154`, and in `local/run_batch.py:88-89`.
   - `run_forge` computes `neg = build_negative(negative)` once.
   - It passes `neg` as the keyword `negative=` to `pipes["gen"]`, which is currently called at `app.py:129`.
   - It passes the same `neg` as the keyword `negative=` to `pipes["rescue"]`, which is currently called at `app.py:140`.
   - The existing positional arguments to both callables are unchanged in order and value. Existing fakes use `lambda *a, **k`, so they already accept the new keyword.
4. **The real pipeline closures in `_load_pipes` accept `negative=NEG` as a keyword with default `NEG`.** These are `gen` at `app.py:53-58` and `rescue` at `app.py:60-64`.
   - Each passes `negative_prompt=negative` instead of `negative_prompt=NEG`.
   - When nothing is passed, the real-generation behaviour is byte-identical to today. This keeps `local/run_batch.py --seed 12345` comparable.
5. **`forge` gets a parameter `negative`.** The current signature is at `app.py:161-166`.
   - It sits between `seed` and `progress`, with default `""`.
   - `forge` forwards it as `run_forge(..., progress=progress, negative=negative)`.
   - The `@GPU(duration=120)` decorator and the `PayloadError → gr.Error` handling stay unchanged.
6. **UI (`build_ui`, `app.py:170-198`): a new `gr.Textbox` inside the existing `gr.Accordion("Advanced", open=False)`.** The accordion is at `app.py:180`.
   - Place the textbox after the `cfg` slider (`app.py:185`) and before the `rescue` checkbox (`app.py:186`).
   - Properties: `label="Negative prompt (added to the built-in list)"`, `lines=2`, `value=""`, `placeholder="e.g. people, hands, red"`.
   - The label and placeholder are UI wording. Per docs/06 §4 they proceed on this default and are flagged in the PR body for Nimrod.
   - The `go.click` inputs list (`app.py:194-195`) becomes `[payload, prompt, batch, weight, steps, cfg, rescue, seed, negative_box]`, in that order. The outputs stay unchanged.

### What does not change
- **THE GATE line** (`app.py:148-149`, `if v["pass"]:  # THE GATE …`), the survivor/reject logic (`app.py:131-149`), and the rescue-eligibility rule (`app.py:139`).
- **Report text.** The header at `app.py:151-154` and the report lines stay the same, and the archive line stays last (`tests/test_gate.py:55`). The negative prompt is not echoed in the report.
- **Reject archive schema.** `settings` at `app.py:155-156` and `build_reject_records` (`app.py:78-91`) do not get a `negative` key. The archive is persisted data (docs/06 §4), and changing its schema is out of scope for this step.
- Everything else stays the same: `validator.py`, `qrbuild.py`, `README.md`, `.github/`, `requirements*.txt`, `docs/`, `local/`, the positive prompt handling, and the defaults of all existing Advanced controls.

## 2. Behaviour table

All rows run on CPU. Generation is mocked through the `pipes=` argument or by monkeypatching `app.run_forge`, as in `tests/test_gate.py:18-22`. The prefix "gen-kw" means the `negative` keyword argument received by the fake `pipes["gen"]`. "rescue-kw" means the same for the fake `pipes["rescue"]`.

| # | Input | Observable result |
|---|---|---|
| 1 | `app.build_negative("")` | returns a string equal to `app.NEG` |
| 2 | `app.build_negative(None)` | equals `app.NEG` |
| 3 | `app.build_negative("   \n\t ")` | equals `app.NEG` |
| 4 | `app.build_negative("people, hands")` | equals `app.NEG + ", people, hands"` |
| 5 | `app.build_negative("  red  ")` | equals `app.NEG + ", red"` (outer whitespace stripped, inner text verbatim) |
| 6 | `app.NEG` | equals the literal `"ugly, disfigured, low quality, blurry, nsfw, text, watermark, flat, grid, checkerboard, monochrome squares"` (unchanged) |
| 7 | `run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=fake)` (no `negative`) | gen-kw `negative == app.NEG` |
| 8 | same as 7 with `negative="people"` | gen-kw `negative == app.NEG + ", people"` |
| 9 | same as 7 with `negative="   "` | gen-kw `negative == app.NEG` |
| 10 | `run_forge(..., rescue=True, ..., negative="people")`, with `app.validate` monkeypatched so the gen image is a near-miss (score ≥ 1, as in `tests/test_gate.py:58-72`) | rescue called exactly once; rescue-kw `negative == app.NEG + ", people"` (the same string gen received) |
| 11 | Row 7 or 8, checking the positional args received by fake gen | positional args are `(prompt, control, batch, weight, steps, cfg, seed)`, exactly as today, with `seed` as the resolved int |
| 12 | Row 8 with the gen fake returning `[GOOD, BAD, BAD]` | survivors/report behave as with no negative: `len(surv) == 1`, `"1/3 passed"` in report, and the last report line is the archive line |
| 13 | Row 8 with `archive_rejects` monkeypatched to capture records | each record's `meta["settings"]` has exactly the keys `{"prompt","batch","weight","steps","cfg","rescue","seed"}` (no `negative` key) |
| 14 | `app.forge(PAY, "p", 1, 1.35, 25, 7, False, 1, "people")` with `app.run_forge` monkeypatched to capture kwargs | captured `negative == "people"` |
| 15 | `app.forge(PAY, "p", 1, 1.35, 25, 7, False, 1)` (negative omitted) with `app.run_forge` monkeypatched | captured `negative == ""` |
| 16 | `app.build_ui()` | exactly one `gr.Textbox` has label `"Negative prompt (added to the built-in list)"`; its `value` is `""` and `lines == 2` |
| 17 | `app.build_ui()` | that Textbox is a descendant of the `gr.Accordion` whose label is `"Advanced"` |
| 18 | `app.build_ui()` | the click dependency of the `gr.Button` labelled `"Forge"` has 9 inputs; input 9 is the negative-prompt Textbox and inputs 1–8 are the same components as today (payload, prompt, batch, weight, steps, cfg, rescue, seed) |
| 19 | `app.build_ui().get_api_info()` | does not raise (existing `tests/test_deploy.py:38` stays green) |
| 20 | Existing suite | every currently green test in `tests/` stays green |

The real-generation check (`local/run_batch.py --seed 12345`, ≥ 2/4) is run by the orchestrator. `run_batch.py` does not pass `negative`, so it exercises row 7's path on the real closures with `negative_prompt == NEG`. No GPU test is specified here.

## 3. Editable paths
- Implementer: `app.py`
- Tester: `tests/` (new test module or additions; existing tests must not be weakened)

The Implementer may not touch `tests/`, `docs/`, `steps/`, `local/`, or any other path.

## 4. Class and lane
- Class: **scoped**. Lane: **ordinary**.
- **Never-economize paths touched: none.** No change to `validator.py`, `qrbuild.py`, `README.md` front-matter, or `.github/`. The diff touches `app.py` and `build_ui` but must not modify the THE GATE line (`app.py:148-149`) or the survivor filter around it. Any diff hunk that changes line 148/149 is a spec violation, and the orchestrator must treat it as never-economize.
- The PR touches `build_ui`, so per docs/06 §4 the orchestrator attaches a screenshot of the Advanced accordion open.

## 5. Blocking questions
None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-6/spec.md)
- Not certain:
  1. **Tester needs to trace Gradio's component tree (rows 17 and 18).** The exact Gradio 5.50 API for walking from a component to its parent Accordion, and for reading a click dependency's input order (`demo.config["dependencies"]` vs `demo.fns`), was not inspected. The Tester must find a stable way to do this.
  2. **The real closures' `negative_prompt=negative` is not checked on CPU.** `_load_pipes` imports torch and diffusers and downloads models, so the change is checked only by the Reviewer reading the diff and by the orchestrator's GPU batch.
  3. **Long negatives get truncated.** CLIP truncates prompts past 77 tokens, and diffusers warns rather than raising, so a very long negative is silently cut. No length cap is specified, because OD 9 did not ask for one.
  4. **The reject archive won't record the user's negative.** This spec keeps the archive schema out of scope. That means rejects generated with a user negative can't be traced to it. Adding it would change persisted data, so it needs its own step and Nimrod's decision.
- Deploy: none
