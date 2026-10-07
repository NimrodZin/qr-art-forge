Class: top · Step: m2-7

# m2-7 — VAE slicing on CUDA behind env flag, default off (P5)

Sources:
- `docs/03_Decisions.md:18`: "P5 VAE slicing on CUDA (≤ 2/255 pixel change; validator runs on final pixels). Off by default until the loop measures pass rate with it on."
- Queue entry: `docs/04_Build_Plan.md:33` (`gpu_env=QRAF_VAE_SLICING=1`).
- Prior art: `local/run_batch.py:39-54` enables the same thing from outside `app.py` with the same variable. It decides on `os.environ.get("QRAF_VAE_SLICING") == "1"` (line 42) and calls `pipe.enable_vae_slicing()` on the txt2img pipeline (line 49).

## 1. Scope

### What changes (app.py only)
1. **New pure helper `vae_slicing_enabled(device: str, env: Mapping[str, str] | None = None) -> bool`**, defined at module level in `app.py`.
   - If `env` is `None`, the helper reads `os.environ` **when it is called**, not when `app` is imported.
   - It returns `True` only if `device == "cuda"` and `env.get("QRAF_VAE_SLICING") == "1"`.
   - Every other value returns `False`. That includes the variable being unset, `""`, `"0"`, `"true"`, `"yes"`, `" 1"` and `"1 "`. Nothing is stripped or lower-cased. This matches `local/run_batch.py:42` and the queue's `gpu_env`.
   - The helper has no other side effects and does not log anything.
2. **`_load_pipes` (`app.py:39-66`) turns on VAE slicing when the helper says so.**
   - It computes `device` exactly as it does now (`app.py:43`).
   - After the txt2img `pipe` is built and its scheduler is replaced (`app.py:46-48`), and before `return` (`app.py:66`), it does this: if `vae_slicing_enabled(device)` is true, it calls `pipe.enable_vae_slicing()` exactly once.
   - Use `pipe.enable_vae_slicing()`, the call `local/run_batch.py:49` already uses. It exists in the pinned `diffusers==0.30.3` (`requirements.txt:2`, `requirements-ci.txt:11`).
   - Do **not** call it on `i2i`. `i2i` is built from `pipe.components` (`app.py:49`), so it shares the same VAE object, and the rescue path gets slicing through that shared VAE.
   - When the flag is off, `_load_pipes` must not call `enable_vae_slicing` or `vae.enable_slicing`, and everything else in it stays as it is today.
3. **Optional, and only if the Implementer wants it:** one short comment next to the call citing P5. It must not be added to any UI string.

### What does not change
- **The default stays off.** Nothing sets `QRAF_VAE_SLICING`: not `app.py`, `README.md`, the Space configuration, nor CI.
- **The `gen` and `rescue` closures** (`app.py:53-64`) stay the same: signatures, arguments, seeds, `width/height=SIZE`. When the flag is off, real generation is byte-identical to today, so the orchestrator's first `run_batch.py --seed 12345` run is still comparable to the recorded md5 (`docs/04_Build_Plan.md:29`).
- **`get_pipes`** (`app.py:69-74`), `make_scheduler` (`app.py:33-36`), `run_forge` (`app.py:126-168`), `forge` (`app.py:171-177`) and `build_ui` (`app.py:181-211`) stay the same. That includes the report text, the header, the archive line and the reject-record `settings` keys (`app.py:165-166`). Slicing is not echoed in the report and not recorded in the archive, because the archive is persisted data (docs/06 §4).
- **The gate is not touched.** That means THE GATE line (`app.py:158-159`), the survivor/reject logic (`app.py:140-159`) and the `validate` calls (`app.py:144`, `app.py:151`). The validator still runs on the final decoded pixels, whatever the VAE decode mode (P5).
- Nothing else changes either: `validator.py`, `qrbuild.py`, `README.md`, `.github/`, `requirements*.txt`, `docs/`, `local/`, `loop/`.

## 2. Behaviour table

All rows run on CPU, with no model downloads and no GPU. In rows 1–8, `env` is passed explicitly unless the row says otherwise.

For rows 9–14, the Tester calls `app._load_pipes()` directly with fakes installed through `monkeypatch`:
- `torch.cuda.is_available` → the stated bool.
- `diffusers.ControlNetModel`, `diffusers.StableDiffusionControlNetPipeline` and `diffusers.StableDiffusionControlNetImg2ImgPipeline` → fake classes. `_load_pipes` imports them inside the function (`app.py:41-42`), so module-attribute patches take effect.
  - The fake `StableDiffusionControlNetPipeline.from_pretrained` returns a recorder object with `.scheduler.config`, `.components` (a dict that includes a sentinel `"vae"`), `.to()`, and a counting `.enable_vae_slicing()`.
  - The fake img2img class records the kwargs it was built with.
- `app.make_scheduler` → identity/no-op.

These tests must not set or leave behind `app._pipes`.

| # | Input | Observable result |
|---|---|---|
| 1 | `app.vae_slicing_enabled("cuda", {"QRAF_VAE_SLICING": "1"})` | `True` |
| 2 | `app.vae_slicing_enabled("cuda", {})` | `False` |
| 3 | `app.vae_slicing_enabled("cpu", {"QRAF_VAE_SLICING": "1"})` | `False` |
| 4 | `app.vae_slicing_enabled("cuda", {"QRAF_VAE_SLICING": v})` for each v in `"0"`, `""`, `"true"`, `"yes"`, `" 1"`, `"1 "`, `"2"` | `False` for every v |
| 5 | `monkeypatch.setenv("QRAF_VAE_SLICING", "1")` **after** `import app`, then `app.vae_slicing_enabled("cuda")` (no `env`) | `True`, which shows the value is read at call time |
| 6 | `monkeypatch.delenv("QRAF_VAE_SLICING", raising=False)`, then `app.vae_slicing_enabled("cuda")` | `False` |
| 7 | `monkeypatch.setenv("QRAF_VAE_SLICING", "1")`, then `app.vae_slicing_enabled("cpu")` | `False` |
| 8 | `app.vae_slicing_enabled("cuda", {"QRAF_VAE_SLICING": "1"})` called twice | the same result both times, and `os.environ` is unchanged afterwards |
| 9 | fakes; `is_available → True`; env `QRAF_VAE_SLICING=1`; `app._load_pipes()` | fake txt2img pipe's `enable_vae_slicing` called **exactly once**; result is a dict with keys exactly `{"gen", "rescue"}` |
| 10 | fakes; `is_available → True`; env var unset | `enable_vae_slicing` called **zero** times |
| 11 | fakes; `is_available → True`; env `QRAF_VAE_SLICING=0` | `enable_vae_slicing` called zero times |
| 12 | fakes; `is_available → False`; env `QRAF_VAE_SLICING=1` | `enable_vae_slicing` called zero times |
| 13 | fakes; `is_available → True`; env `QRAF_VAE_SLICING=1` | the fake img2img was built with a `vae` kwarg that **is** (identity) the sentinel VAE in the txt2img pipe's `components`, so rescue shares the sliced VAE; the img2img fake's own `enable_vae_slicing` (if the fake has one) is called zero times |
| 14 | row 9 vs row 10 | apart from the `enable_vae_slicing` call, the fakes see the same calls in both: the `from_pretrained` args/kwargs (`BASE`, `controlnet=`, `torch_dtype=`, `safety_checker=None`) and `.to("cuda")` on both pipes |
| 15 | `run_forge(PAY, "p", 3, 1.35, 25, 7, True, 1, pipes=fake)` with `QRAF_VAE_SLICING=1` set | the report and survivors are identical to the same call with the variable unset (`"1/3 passed"`, last line is the archive line, as in `tests/test_gate.py:25-55`). The flag has no effect outside `_load_pipes` |
| 16 | existing suite | every test in `tests/` that is green now stays green |

The orchestrator runs the real-generation check itself (`local/run_batch.py --seed 12345` ≥ 2/4, once without and once with `QRAF_VAE_SLICING=1`, per docs/06 §1a). No GPU test is specified here.

## 3. Editable paths
- Implementer: `app.py`
- Tester: `tests/`. Add a new module, e.g. `tests/test_vae_slicing.py`. Existing tests must not be weakened.

The Implementer may not touch `tests/`, `docs/`, `steps/`, `local/`, `loop/`, or any other path.

## 4. Class and lane
- Class: **scoped**. Lane: **ordinary**.
- **Never-economize paths touched: none.** The step does not change `validator.py`, `qrbuild.py`, `README.md` front-matter or `.github/`.
- The `app.py` diff must sit inside `_load_pipes` plus the new module-level helper (and a `Mapping` import if one is needed). It must not touch THE GATE line (`app.py:158`), the `run_forge`/`forge` spans (`app.py:126-177`), or any `validate` token. Any hunk there is a spec violation and must be treated as never-economize, which means the step stops.
- There are no UI string changes, so no `ui-change` label.

## 5. Blocking questions
None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-7/spec.md)
- Not certain:
  1. **The second GPU run can't tell whether `app.py`'s own hook works.** `local/run_batch.py:39-54` enables slicing on its own whenever `QRAF_VAE_SLICING=1`, by wrapping `from_pretrained`. So that run exercises slicing even if this step's code is wrong. Calling it twice is harmless (it just sets a flag on the shared VAE). For this step, the proof that `app.py` itself enables slicing rests on rows 9–14 plus the Reviewer. `local/` is git-ignored and outside every editable path, so removing the wrapper would be a manual PC-side change for the planner/Nimrod.
  2. **Faking diffusers' lazy module.** Rows 9–14 assume `monkeypatch.setattr(diffusers, "<Class>", Fake)` works on diffusers 0.30.3's `_LazyModule`. The first `getattr` imports the real class, and the patched attribute then shadows it. I didn't run this. If it fails, the Tester may patch through `sys.modules` instead or report BLOCKED.
  3. **Pixel change and pass rate are not measured here.** P5's "≤ 2/255 pixel change" comes from `local/REPORT-local.md` (cmp_slice rows, 4/4 at seed 12345) and is not re-measured in this step. The default stays off. Flipping it on is a separate decision once the loop has measured the pass rate.
- Deploy: none
