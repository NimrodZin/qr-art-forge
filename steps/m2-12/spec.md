Class: top · Step: m2-12

# m2-12 — Shadow-style centre repair: spec

Sources: docs/04_Build_Plan.md:38 (queue line), docs/05_Open_Discussion.md:16 (OD 12 step 2), docs/05_Open_Discussion.md:17 (F1 results). The research note `claude/research-perception.md` is not in this repo. Not found. Nothing in this spec depends on it.

## 1. Scope

### What changes

**New module `repair.py`.** It is pure and deterministic, and runs on CPU only.
- Allowed imports: stdlib, `numpy`, `PIL`, and `qrcode` (only for the alignment-pattern table, `qrcode.util.pattern_position`).
- It must not import `validator`, `zxingcpp`, `cv2`, `torch` or `diffusers`. Repair cannot see the decoder.
- It never receives the payload. Payload handling stays in `qrbuild.py:19-34`.

Public names in `repair.py`:

| Name | Value / signature |
|---|---|
| `WINDOW` | `3` (modules, side of the threshold window) |
| `CENTRE` | `0.15` (centre-sample radius, fraction of a module) |
| `RADIUS` | `0.3` (dot core radius, fraction of a module) |
| `FEATHER` | `0.2` (Gaussian σ, fraction of a module) |
| `SUPPORT` | `RADIUS + 3*FEATHER` (= 0.9) |
| `MARGIN` | `0.15` (OKLab L units, 0..1) |
| `repair_enabled(env: Mapping[str,str] | None = None) -> bool` | `env` defaults to `os.environ`. Returns `env.get("QRAF_REPAIR") != "0"`. Same pattern as `app.py:43-47`. |
| `to_oklab(rgb: np.ndarray) -> np.ndarray` | uint8 H×W×3 sRGB → float64 H×W×3 (L, a, b). Standard sRGB transfer (0.04045 / 12.92 / 2.4) and Ottosson's OKLab matrices (2020). White → (1, 0, 0). |
| `from_oklab(lab: np.ndarray) -> np.ndarray` | Inverse transform. Clips linear RGB to [0, 1], rounds to nearest, returns uint8. |
| `module_grid(control: Image) -> Grid` | `Grid` has `module` (px), `offset` (px), `n` (modules per side including the 4-module quiet zone), `version`, and `dark` (bool n×n). Derived only from the control image's pixels. See row P1. |
| `skip_mask(grid) -> np.ndarray` | bool n×n. True on skipped modules. See row P2. |
| `repair(image: Image, control: Image) -> tuple[Image, int]` | Returns a new RGB image and `k`, the number of modules touched. The input is never mutated. |

**Repair algorithm.** It runs once, on the input image's OKLab L. All geometry is in pixels, with m = `grid.module`.
- **Module centre.** For module (r, c): (cx, cy) = (offset + (c + 0.5)·m, offset + (r + 0.5)·m). Pixel (x, y) sits at (x + 0.5, y + 0.5). d is the Euclidean distance from the pixel to the centre.
- **Threshold.** T = mean L over the axis-aligned square of side WINDOW·m centred on the module centre, clipped to the image.
- **Centre value.** Lc = mean L over pixels with d ≤ max(CENTRE·m, 0.71).
- **Flagging.** A non-skipped module is flagged when it is not on its correct side by at least MARGIN:
  - dark module: flagged iff Lc > t, where t = max(0, T − MARGIN)
  - light module: flagged iff Lc < t, where t = min(1, T + MARGIN)
  - k = number of flagged modules.
- **Dot weight.** w(d) = 1 for d ≤ RADIUS·m. For RADIUS·m < d < SUPPORT·m, w(d) = exp(−(d − RADIUS·m)² / (2·(FEATHER·m)²)). Otherwise w = 0.
- **Darkening field.** D(p) = max over flagged dark modules of w·max(0, L(p) − t).
- **Lightening field.** U(p) = max over flagged light modules of w·max(0, t − L(p)).
- **Dark zone.** Z = pixels with d < SUPPORT·m from any flagged dark module's centre.
- **New lightness.** L′ = L − D inside Z. L′ = L + U outside Z. So a repaired dark centre's ring is never brightened, and each module moves in one direction only.
- **Re-encoding.** Pixels whose L′ ≠ L are re-encoded with their original a and b. All other pixels keep their input bytes exactly.
- **Skipped cells.** Pixels inside the m×m cell of any skipped module are never changed.

**Wiring in `app.py` `run_forge` (`app.py:166-212`).**
- `app.py` adds `import repair` next to `app.py:13-14`. It calls the function through the module attribute, `repair.repair(...)`, so tests can monkeypatch it.
- `repair_on = repair.repair_enabled()` is read once per `run_forge` call, not at import time.
- In the per-candidate loop, after `v = validate(im, payload)` (`app.py:187`) and the existing reject append (`app.py:189-190`):
  - When `repair_on and not v["pass"] and v["score"] >= 1`, call `im_r, k = repair.repair(im, control)`. `control` is the `make_qr` image from `app.py:173`.
  - If k == 0: append `" → repair 0: unchanged"` to `tag` and do not call `validate`.
  - Else: `v_r = validate(im_r, payload)` and append `f" → repair {k}: " + summary_line(v_r)` to `tag`.
  - If `v_r["pass"]`: set `im, v = im_r, v_r`.
- **Rescue is unchanged** (`app.py:191-199`). It runs only if `v` still does not pass. It then uses the original `im`, the original `v["score"]` and the same arguments as on main.
- **Archive.** The original reject is archived as today. A failed repaired image is not archived. `build_reject_records` (`app.py:115-131`) and its metadata do not change.
- `THE GATE` (`app.py:201`) stays byte-identical and remains the only append to `survivors`. The caption (`app.py:202`), header (`app.py:204-207`), `settings` (`app.py:208-209`), `forge` and UI layout are unchanged.

### What does not change
- `validator.py`, `qrbuild.py`, `README.md`, `.github/` and `requirements.txt`.
- `docs/` (02 v0.4 is unchanged. Repair is a pre-gate pixel step. The invariant at `02:32-33` holds because `validate` runs on the exact pixels that reach the gallery.)
- The rescue policy (`02:22-24`) and the archive schema (P4, `03:17`).
- The existing test suite must stay green without edits. For example, `tests/test_gate.py:64-74` and `tests/test_rejects.py:164-197` now also exercise a real repair of `BAD`, which must still fail and must not be archived.
- The repair step adds no progress call.

## 2. Behaviour table (all CPU; generation mocked; "real validate" means `validator.validate`)

### Pure `repair.py`

| # | Input | Observable result |
|---|---|---|
| P0 | Module constants | `WINDOW==3`, `CENTRE==0.15`, `RADIUS==0.3`, `FEATHER==0.2`, `MARGIN==0.15`, `SUPPORT==RADIUS+3*FEATHER`. The import scan of `repair.py` finds none of `validator`, `zxingcpp`, `cv2`, `torch`, `diffusers`. |
| P1 | `module_grid(make_qr(p))` for `p` in `"abc"` (v1), `"https://nimrodzin.com"` (v3), and an 80-char payload | `module == 768 // n`. `n == qrcode modules_count + 8`. `offset == (768 - n*module)//2`. `version` equals the qrcode version. `dark` equals `qrcode.QRCode(error_correction=H, border=4).get_matrix()` for the same payload. |
| P2 | `skip_mask(module_grid(make_qr(p)))` for the same three payloads | True exactly on: the 4-module quiet-zone border; three 8×8 finder-plus-separator blocks (grid rows/cols 4..11 and n−12..n−5, at the top-left, top-right and bottom-left corners); every 5×5 alignment pattern centred on pairs of `qrcode.util.pattern_position(version)`, offset by +4, except the three pairs that overlap finders. Version 1 has no alignment patterns. |
| P3 | `to_oklab` / `from_oklab` | White → L 1 ± 1e-3, \|a\|, \|b\| ≤ 1e-3. Black → (0, 0, 0) ± 1e-6. Grey 128 → L 0.600 ± 0.002. Round trip of all 256 greys and 1000 seeded random colours: max channel error ≤ 1. |
| P4 | `repair(c, c)` where `c = make_qr("https://nimrodzin.com")` | `k == 0` and output bytes equal input bytes. |
| P5 | `repair(x, c)` called twice | The input image bytes are unchanged afterwards. Both calls give identical bytes and k. The output is mode RGB and the same size. |
| P6 | Flat RGB(128,128,128) 768² candidate with `c` from P4 | `k ==` number of non-skipped modules. The output is unchanged on every skipped cell and outside the symbol square. For each flagged module, the 1–4 pixels nearest its centre satisfy (tolerance 0.01; T = L(128) because the image is flat): dark: L′ ≈ T − MARGIN; light: L′ ≈ T + MARGIN. |
| P7 | Candidate = `c` with flat grey painted over a few chosen data modules | Flagging matches the rule in §1 (k equals the expected count). Pixels farther than SUPPORT·m from every flagged module's centre are byte-identical. |
| P8 | Any flagged dark module (fixtures P6, P7) | Every pixel with d < SUPPORT·m of its centre has output L ≤ input L + 0.01. Nothing is brightened around a repaired dark centre. |
| P9 | Light flagged modules (P6, P7) | Pixels with d ≤ RADIUS·m of the centre and outside every dark zone have output L ≥ input L − 0.01. |
| P10 | A neutral-grey candidate, and a candidate with moderate in-gamut colours (\|a\|, \|b\| ≤ 0.08, no channel at 0 or 255 after repair) | Neutral changed pixels stay neutral (R == G == B). Coloured changed pixels have \|Δa\|, \|Δb\| ≤ 0.02 against the input. |
| P11 | `repair(img, c)` with `img.size != c.size` | Raises `ValueError`. |
| P11b | `module_grid` of a flat grey 768² image | Raises `ValueError`. |
| P12 | `repair_enabled({})`, `({"QRAF_REPAIR": "1"})`, `({"QRAF_REPAIR": "x"})`, `({"QRAF_REPAIR": "0"})`; with no argument, reads `os.environ` (monkeypatched) | `True`, `True`, `True`, `False`. The no-argument call follows the monkeypatched environment. |
| P13 | End-to-end with real validate. Fixture: `c` from P4. On a deterministic subset of non-skipped data modules (for example, every module with (r·7 + c·3) mod 3 == 0), paint a disc of radius 0.2·m at the module centre in the opposite colour. | Precondition: `validate(fixture, "https://nimrodzin.com")["pass"] is False`. The Tester may raise the fraction, or the disc radius up to 0.3·m, until it fails, and records the recipe. `out, k = repair(fixture, c)`: `k ==` subset size and `validate(out, ...)["pass"] is True`. |

### `run_forge` wiring

Uses fake pipes, a monkeypatched `app.validate` where needed, and a spy or monkeypatch on `repair.repair`.

| # | Input | Observable result |
|---|---|---|
| A1 | `QRAF_REPAIR=0`. Candidates: one passing, one score-0 fail, one score-1 fail (rescue on, and rescue off). `repair.repair` patched to raise. | Never raises. Survivors, report text and archive records equal main's behaviour: each tag is `"seed N: " + summary_line(v)` plus, if rescued, `" → rescue " + summary_line(v2)`. No "repair" substring anywhere in the report. |
| A2 | Repair enabled (env unset). Candidate passes. | `repair.repair` not called. Tag unchanged. |
| A3 | Enabled. Fail with score 0. | `repair.repair` not called. Rescue not called. Tag unchanged. |
| A4 | Enabled. Score ≥ 1 fail. The repair spy returns `(R, 5)`. `validate(R)` passes. Rescue on. | `repair.repair` called exactly once, with `(the original candidate object, the control object run_forge returns)`. Rescue not called. The survivor is the exact `R` object that `validate` returned pass for. Tag == `"seed N: " + summary_line(v) + " → repair 5: " + summary_line(v_R)`. Archive labels == `["seedN"]` with the original pixels. |
| A5 | Enabled. Score ≥ 1. Repair returns `(R, 5)`, `R` fails. Rescue on and passes. | Rescue called once, with the original candidate as its image and the same positional and keyword arguments as on main. The survivor is the rescued image. Tag == `orig + " → repair 5: " + summary(FAIL) + " → rescue " + summary(PASS)`. Archive labels `["seedN"]`. `R`'s bytes are not in any record. |
| A6 | As A5 but rescue fails | No survivor. Archive labels `["seedN", "seedN-rescue"]`, and neither record holds `R`'s bytes. |
| A7 | Enabled. Score ≥ 1. Repair returns `(X, 0)`. | `validate` is not called on `X`. Tag contains `" → repair 0: unchanged"`. Rescue then behaves as on main. |
| A8 | Enabled. Score ≥ 1. Rescue checkbox off. | Repair is still called. A passing repair is a survivor. Rescue never called. |
| A9 | Enabled. Batch of 3 mixed candidates, with spies on `validate` and `repair.repair`. | Repair is called at most once per candidate. Every survivor image is an object that `validate` returned `pass: True` for. The header reads `"{survivors}/3 passed."`. |
| A10 | `monkeypatch.setenv("QRAF_REPAIR", "0")` after `import app` | The next `run_forge` call does not repair (env read per call). |
| A11 | Enabled. `reference=` and `negative=` given | Repair arguments are unaffected (`(im, control)` only). Rescue keyword arguments are as on main. |
| A12 | `app.py` source | The line `        if v["pass"]:  # THE GATE — the only way into the gallery` exists exactly once. `survivors.append` occurs exactly once, inside it. |

## 3. Editable paths

`repair.py,app.py,tests/`
- Tester: `tests/` only.
- Implementer: `repair.py` (new) and `app.py` only. Never `tests/`, `docs/` or `steps/`.

## 4. Class and lane

- **Class:** top. **Lane:** never-economize.
- **Never-economize paths touched:** yes. The diff edits the gate span (`run_forge`, `app.py:166-212`) and adds a `validate` call. `THE GATE` line (`app.py:201`) must stay byte-identical.
- **Not touched:** `validator.py`, `qrbuild.py`, `README.md` front-matter and `.github/`.
- **Merge:** the orchestrator must not auto-merge. The PR stops for Nimrod (STATE: lane closed).
- **Labels:** the report text gains new tokens (`→ repair k: …`), so flag the PR as `ui-change` (06 §4, `06:49`).
- **GPU:** the real-generation check is run by the orchestrator, with the default env and with `QRAF_REPAIR=0`, per the queue line.
- **Hand gate (Nimrod, not CI):** apply `repair.repair` directly to the four photoreal strength-0.9 images of F1 run 20261017-143330, using `make_qr(<F1 payload>)`. Then:
  - count how many pass `validate`;
  - phone-scan the survivors;
  - judge whether the dots read as shadow or as dots.

## 5. Blocking questions

None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-12/spec.md)
- Not certain:
  1. **Trigger vs acceptance.** The queue line's trigger (score ≥ 1) never fires on the acceptance set: every F1 strength-0.9 candidate scored 0/3 (`05:17`, `tests/test_f1.py:38-40`). So the hand gate must call `repair.repair` directly (§4), and inside `forge` repair will not help at 0.9. Widening the trigger to score 0 is a planner/Nimrod follow-up. Recommendation: decide after the hand gate.
  2. **Flagging margin.** "Wrong side of the local threshold" is implemented as "not on the correct side by MARGIN = 0.15". Without the margin, a flat grey image flags nothing, and ties at uniform black or white are ambiguous. CENTRE = 0.15, the 3σ support and the dark-zone rule are also Architect rulings, tunable at the hand gate. The threshold is computed in OKLab L, not in zxing's luma, so "LocalAverage-style" is an approximation.
  3. **Separators.** Finder separators are skipped together with the finders (8×8 blocks). The queue line names only the finder patterns.
  4. **Archive.** Failed repaired images are not archived, so the archive schema is unchanged. Archiving them would be a persisted-data decision (P4) for Nimrod.
  5. **docs/02.** Not amended. Its Rescue and Output sections (`02:22-30`) do not mention repair. Contract text may be wanted when OD 12 resolves.
  6. **P13 fixture.** Its robustness is empirical. The Tester may need to tune the recipe within the stated bounds.
  7. **Research note.** `claude/research-perception.md` was not found in the repo and was not read.
- Deploy: none
