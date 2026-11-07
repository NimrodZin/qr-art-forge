Class: top · Step: m2-14

# m2-14: Validator 02 v0.5: a thin candidate no longer passes

Sources:
- `docs/02_Core_Spec.md:18`: "**Pass** ⇔ D succeeds on `full` and on `small`, and `small` hit_count ≥ 2."
- `docs/02_Core_Spec.md:19`: "`thin` = D succeeds on `full` and on `small` and `small` hit_count = 1; a thin candidate does not pass (v0.5) and, with score ≥ 1, stays rescue-eligible."
- `docs/03_Decisions.md:8` (D3) and the queue entry at `docs/04_Build_Plan.md:39`.

## 1. Scope

The contract is already at v0.5. This step brings the code and tests into line with it and does not change `docs/`.

### What changes in `validator.py` (Implementer)

**The pass rule, at `validator.py:102-105`.** Today `passed` comes from the gates alone, and `thin` requires a pass, so a thin candidate passes.

- Keep `passed = all(results[c]["zx"] for c in GATES)` (`validator.py:103`) byte-for-byte, and keep it occurring exactly once in the file. Calibration seed 10 targets it (`loop/seeds/10-pass-rule-off-by-one.json:3`), and `tests/test_calibrate.py:50,68` enforces this.
- Add the margin rule after that line.
- Compute `thin` from the gate result, before the margin rule is applied. Otherwise `thin` could never be true.

Suggested form:

```python
passed = all(results[c]["zx"] for c in GATES)
thin = passed and results["small"]["hit_count"] == 1
passed = passed and results["small"]["hit_count"] >= 2
return {"pass": passed, "score": score, "max": len(results), "results": results, "thin": thin}
```

Requirements on any equivalent form:
- `pass` and `thin` stay plain Python `bool`, because the archive serialises the result (`app.py:127-128,150`).
- The margin applies to `small` only. It does not apply to `full` or `tilt`.
- The result keeps exactly the same keys.

**Text that becomes false.** No behaviour depends on these:
- The module docstring (`validator.py:1-4`) says "docs/02 v0.4" and "passes only if … on `full` and `small`".
- The `validate` docstring (`validator.py:90-94`) says "pass needs it on full and small" and "'thin' flags a pass".

### What changes in `tests/` (Tester)

Three existing tests expect a thin pass and must be updated:

| Test | Today | Under v0.5 |
|---|---|---|
| `tests/test_validator.py:346-350` | `pass` True, `thin` True | `pass` False, `thin` True |
| `tests/test_f1.py:43-46` (`photoreal_s1.1_plain_12347_3`) | `pass` True, `thin` True | `pass` False, `thin` True |
| `tests/test_f1.py:18-20,31-35` (`test_tilt_only_rejects_now_pass`) | all 3 images pass | **2 of 3 now fail** |

**The queue entry does not name the third test.** `tests/test_f1.py:18-20` lists three images, and two of them are thin on `small`:
- `photoreal_s1.1_plain_12348_4` has `small=GH@S2` (`local/f1/20261017-143330/manifest.csv:14`).
- `dreamshaper_s1.1_plain_12346_2` has `small=LA@S2` (`manifest.csv:38`).
- Only `dreamshaper_s1.1_dappled_12348_4` still passes, with `small=FT@S1+LA@S2+FT@S2` (`manifest.csv:45`).

The queue's instruction to update tests that expect a thin pass covers this test. Split it as in rows 22-24 below.

These tests only need rewording, because their assertions still hold:
- `tests/test_validator.py:360-367`: the name `test_v4_thin_needs_a_pass` and the comment "a fail is never thin" are now wrong. Rename it to say thin needs `full` and `small`.
- `tests/test_f1.py:1`: the docstring says 02 v0.4.

`test_f1` is skipped in CI (`tests/test_f1.py:15-16`, `pytest.ini:6`). It runs only in the suite on the PC, where the run folder exists.

### What does not change

- **D and the conditions:** D, softening, the three conditions, `hits` order, `hit_count`, and `GATES` (`validator.py:26`, pinned at `tests/test_validator.py:377`).
- **Scoring and OpenCV:** the score (`validator.py:102`) still counts `tilt`, and OpenCV stays advisory.
- **`summary_line` (`validator.py:108-113`):** its format is pinned by `tests/test_validator.py:86-87,95`. A thin candidate reads `FAIL full zx✓ … | small zx✓ … (n/3)`. See Not certain 2.
- **`app.py`:**
  - The rescue condition `v["score"] >= 1` (`app.py:191`) already makes every thin candidate eligible, because a thin candidate has score ≥ 2.
  - The gate (`app.py:201`) reads `v["pass"]`, so thin candidates are kept out of the gallery with no edit there.
  - No code outside `validator.py` and `tests/` reads `thin`.
- **Everything else:** archive schema (`app.py:127-129`), `qrbuild.py`, default generation settings, `docs/`, `local/`, `loop/`, and `README.md`.

## 2. Behaviour table

Everything runs on CPU with generation mocked.

### Pass, thin and score, with hits stubbed per condition

Rows 1-13 stub `validator._phone_hits` per condition, extending `_hit_conditions` (`tests/test_validator.py:272-283`). The numbers are the length of the list returned for each condition. In every row:
- `results[c]["zx"]` is `bool(hits)`.
- `results[c]["hits"]` is the stubbed list.
- `results[c]["hit_count"]` is its length.
- `max` is 3.

| # | full | small | tilt | `pass` | `thin` | `score` | Why |
|---|---|---|---|---|---|---|---|
| 1 | 2 | 2 | 2 | True | False | 3 | The boundary of the margin |
| 2 | 1 | 2 | 0 | True | False | 2 | The margin is on `small` only, and `tilt` does not gate |
| 3 | 9 | 9 | 9 | True | False | 3 | Maximum hits |
| 4 | 2 | 3 | 1 | True | False | 3 | One hit on `tilt` has no effect |
| 5 | 2 | 1 | 2 | False | True | 3 | Thin, even at a full score |
| 6 | 9 | 1 | 0 | False | True | 2 | Thin; many hits on `full` do not compensate |
| 7 | 1 | 1 | 1 | False | True | 3 | Thin |
| 8 | 0 | 1 | 2 | False | False | 2 | `full` misses, so not thin |
| 9 | 0 | 2 | 2 | False | False | 2 | The margin does not replace the `full` gate |
| 10 | 2 | 0 | 2 | False | False | 2 | `small` misses, so not thin |
| 11 | 1 | 0 | 0 | False | False | 1 | Gate miss |
| 12 | 0 | 0 | 1 | False | False | 1 | `tilt` only |
| 13 | 0 | 0 | 0 | False | False | 0 | Nothing decodes |

### Real decode with `_zx_read` stubbed

These rows use `_small_hits_only` (`tests/test_validator.py:334-343`) on `make_qr(PAY)`.

| # | Input | Result |
|---|---|---|
| 14 | `small` hit by LA@S0 only | `pass` False, `thin` True, `score` 3. `small` `hits` is `["LA@S0"]`, `hit_count` 1. |
| 15 | Same input as row 14, `summary_line(v)` | Starts with `FAIL `, contains `small zx✓`, ends with `(3/3)`. |
| 16 | `small` hit by LA@S0 and GH@S0 | `pass` True, `thin` False. `hits` is `["LA@S0", "GH@S0"]`. |
| 17 | Any thin result | `v["pass"] is False` and `v["thin"] is True`, as plain bools. `set(v)` is `{"pass", "score", "max", "results", "thin"}`. `json.dumps(v)` succeeds. |
| 18 | Unstubbed clean QR | `pass` True, `thin` False, `score` 3, `small` `hit_count` > 1. |

### Through `app.run_forge`, with mocked pipes

Use a wrapper around `app.validate` that calls the real `validator.validate` under a `_phone_hits` stub chosen per candidate. Don't return a hand-built result dict, because these rows must exercise the real rule. `app.py` is not edited, so these pin the gate and rescue against the new rule.

| # | Input | Result |
|---|---|---|
| 19 | One thin candidate, `rescue=False` | No survivors, report contains `0/1 passed`, rescue pipe not called, and the candidate is passed to the reject archive as `seed<N>`. |
| 20 | One thin candidate, `rescue=True`, rescue returns a non-thin passing image | Rescue pipe called exactly once. The only survivor is the rescued image, not the original. Report contains `→ rescue PASS`. |
| 21 | One thin candidate, `rescue=True`, rescue returns a thin image | No survivors, report contains `→ rescue FAIL`. Both are passed to the reject archive, as `seed<N>` and `seed<N>-rescue`, each with `pass` False. |

### F1 phone-truth set (`f1` marker, PC only, real images, no stubs)

| # | Image | Result |
|---|---|---|
| 22 | `photoreal_s1.1_plain_12347_3` | `pass` False, `thin` True, `score` 3, `small` `hits` `["LA@S2"]` |
| 23 | `photoreal_s1.1_plain_12348_4` and `dreamshaper_s1.1_plain_12346_2` | `pass` False, `thin` True, `score` 2, `tilt` `zx` False; `small` `hits` are `["GH@S2"]` and `["LA@S2"]` |
| 24 | `dreamshaper_s1.1_dappled_12348_4` | `pass` True, `thin` False, `score` 2, `tilt` `zx` False, `small` `hit_count` 3 |
| 25 | Rescued versions of the two images in row 23 (`manifest.csv:15,39`) | `pass` True, `thin` False |
| 26 | The 16 strength-1.35 rows (`manifest.csv:21-28,47-54`) | `pass` True, `thin` False, `small` `hit_count` ≥ 2 |
| 27 | All 53 manifest rows | `thin` is True on exactly the 3 files in rows 22-23 |

### Unchanged guards

| # | Check | Result |
|---|---|---|
| 28 | `tests/test_calibrate.py` seed checks | Stay green. Seed 10's line occurs exactly once in `validator.py`. The seed 7 line (`validator.py:65`) and seed 9 line (`validator.py:83`) are untouched. |
| 29 | `tests/test_f1.py:59-65` (`test_hits_match_f1_batch_encoding`) | Stays green. Hits and score are unchanged. |
| 30 | Full suite | Everything else that is green on main stays green, including `tests/test_gate.py`, `tests/test_reference.py`, `tests/test_rejects.py`, and `tests/test_validator.py:286-301`. |

## 3. Editable paths

- Implementer: `validator.py`
- Tester: `tests/`

The orchestrator runs the real-generation check (`local/run_batch.py --seed 12345`, ≥ 2/4), so no GPU test is specified here.

## 4. Class and lane

Class **top**, lane **never-economize**.

The step touches a never-economize path: `validator.py`, including its pass semantics. It does not touch `qrbuild.py`, `README.md`, `.github/`, or the THE GATE line in `app.py` (`app.py:201`). The orchestrator will not auto-merge this diff.

## 5. Blocking questions

None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-14/spec.md)
- Not certain:
  1. **v0.5 rejects two images that read on both phones.**
     - `photoreal_s1.1_plain_12348_4` and `dreamshaper_s1.1_plain_12346_2` read 3/3 on iPhone and Android (`docs/05_Open_Discussion.md:17`). They were part of the evidence for v0.4 (`docs/02_Core_Spec.md:41`).
     - The rule at `docs/02_Core_Spec.md:18` is unambiguous, so I did not block. Both still have rescued versions that pass (`manifest.csv:15,39`).
     - The v0.5 provenance says of F1 "both thin passes failed on iPhone" (`docs/02_Core_Spec.md:42`). OD 13 names one thin failure (`photoreal_s1.1_plain_12347_3`), and the manifest shows three thin images. The planner should check that wording when reading the diff.
  2. **The report line doesn't explain a thin failure.** It can read `FAIL full zx✓ … | small zx✓ … (3/3)`, which looks contradictory. Fixing it is a UI wording change outside this title, so it is left as is; a small follow-up is worth considering.
  3. **The archive record omits `thin`.** `docs/02_Core_Spec.md:29` says the record "carries the full report dict", but `app.py:127-129` leaves `thin` out, and `tests/test_reference.py:22-23` pins those keys. This predates the step, and `thin` can be derived from the recorded `results`. Changing it would be a persisted-data decision for Nimrod, so it is out of scope.
  4. **The margin at 1.35 is narrower than "16/16" suggests.** I confirmed 16/16 from the manifest, but one image sits at exactly 2 (`manifest.csv:49`) and one at 3 (`manifest.csv:25`). Prompts outside F1 are unmeasured here, and the GPU gate covers only peony at seed 12345.
  5. **Calibration is not re-proved.**
     - Seed 10 should still be a real defect after the margin rule: under `any`, a candidate that misses `full` with `small` hits ≥ 2 would pass, and `tests/test_validator.py:286-294` catches that. This is from reading the code, not from a run.
     - The seed's defect text still says 02 v0.4 (`loop/seeds/10-pass-rule-off-by-one.json:5`).
     - Mutation testing on the new lines is not re-run by this step. Rows 1, 2, 5 and 9 are chosen to kill the obvious mutants of the new rule.
  6. **F1 expectations come from the manifest, not a run.** Rows 22-27 use its recorded hits, which `tests/test_f1.py:59-65` pins to the current decoder. I did not execute them.
- Deploy: none
