Class: top · Step: m2-7b

# m2-7b: VAE slicing on by default (P5 decided); `QRAF_VAE_SLICING=0` turns it off

Sources:
- `docs/03_Decisions.md:18`: "P5 VAE slicing on CUDA (≤ 2/255 pixel change; validator runs on final pixels). DECIDED 2026-10-07: ON by default, QRAF_VAE_SLICING=0 disables." The same line records the measurement: without slicing, 4×768 peaks at 12.7 GB reserved on the 4070, spills to host RAM and takes 752 s. With slicing it peaks at 6.0 GB and takes 22.5 s. Both runs passed 4/4.
- Queue entry: `docs/04_Build_Plan.md:34` (`gpu_env=QRAF_VAE_SLICING=0`).
- Prior step: `steps/m2-7/spec.md` added the env flag with the default off. Its tests are in `tests/test_vae_slicing.py`.

## 1. Scope

### What changes in `app.py` (Implementer)
Only the helper `vae_slicing_enabled` (`app.py:39-43`) changes.
- The signature stays the same: `vae_slicing_enabled(device: str, env: Mapping[str, str] | None = None) -> bool`.
- If `env` is `None`, the helper reads `os.environ` **when it is called**. This is the current behaviour at `app.py:41-42` and it stays.
- New rule: it returns `True` if and only if `device == "cuda"` and `env.get("QRAF_VAE_SLICING") != "0"`.
  - **Only the exact string `"0"` turns slicing off.** Nothing is stripped or lower-cased. That means unset, `"1"`, `""`, `"false"`, `"off"`, `"no"`, `" 0"`, `"0 "`, `"00"` and `"2"` all leave slicing **on** when the device is CUDA.
  - On any device other than `"cuda"` it returns `False`, whatever the variable says. P5 is CUDA-only.
- The docstring is updated to match, for example: "P5 (decided 2026-10-07): VAE slicing on CUDA by default; QRAF_VAE_SLICING=0 disables."
- The helper has no side effects and does not log anything. That is already true and stays true.

The call site in `_load_pipes` (`app.py:59-60`, `if vae_slicing_enabled(device): pipe.enable_vae_slicing()  # P5`) does not change. It stays in the same position, it is still called once on the txt2img `pipe` only, and it is still never called on `i2i`. `i2i` is built from `pipe.components` (`app.py:56`), so it shares the VAE, and rescue gets slicing through that shared VAE.

### What changes in `tests/` (Tester)
1. **Rewrite `tests/test_vae_slicing.py` for the new default.** Some of its m2-7 assertions now contradict P5 as decided (`docs/03_Decisions.md:18`). Replacing those is not weakening the suite: each is replaced by its inverse under the new decision.
   - Row 2, `test_cuda_without_flag_is_false` (`:23-24`).
   - Row 4, `test_only_exact_one_enables` (`:31-33`).
   - Row 6, `test_env_unset_is_false` (`:41-43`).
   - Row 10, `test_flag_unset_does_not_enable` (`:138-142`).
   - Row 14, `test_flag_changes_nothing_else_in_load` (`:168-183`). It compares `"1"` against unset, which are now both "on".
   - Row 15, `test_flag_has_no_effect_on_run_forge` (`:187-199`). It should compare `"0"` against unset.
   - Keep the fake harness at `:60-127` as it is. That includes `install_fakes`, the sentinel `VAE` and the `keep_pipes_cache` fixture.
   - Update the module docstring (`:1`) to cite this spec.
2. **Fix `tests/test_loop.py::test_real_build_plan_queue_parses` (`:136-145`).** By reading, I believe it is red on main at `fae5712` (not run; see Not certain 1).
   - It asserts `[s.id for s in steps][:3] == ["m2-6", "m2-7", "m2-5"]` and `not steps[1].done`.
   - The live queue (`docs/04_Build_Plan.md:32-35`) is m2-6 [x], m2-7 [x], m2-7b [ ], m2-5 [ ].
   - Rewrite it so it looks steps up **by id**, not by position. It must not assert m2-7b's done state, because the Merger flips that box after this step merges (`loop/queue.py:89-99`) and the assertion would turn red on main.
   - It must keep every other fact the test checks today: m2-6's paths, class, lane, `touches_gpu` and done state; m2-7's class, lane, `touches_gpu` and `gpu_env`; m2-5's class and lane.

### What does not change
- **`_load_pipes` beyond the helper it calls.** That covers the device and dtype choice (`app.py:50-51`), model loading (`:52-56`), `.to(device)` (`:57-58`), the slicing call site (`:59-60`), and the `gen`/`rescue` closures (`:62-73`).
- **The rest of `app.py`:** `get_pipes` (`:78-83`), `make_scheduler` (`:33-36`), the reject archive (`:87-124`), `build_negative` (`:128-132`), `run_forge` (`:135-177`), `forge` (`:180-186`) and `build_ui` (`:190-220`).
  - Slicing is not echoed in the report and not added to the reject-record `settings` (`app.py:174-175`), because those settings are persisted data (docs/06 §4).
- **The gate.** THE GATE line (`app.py:167-168`), the survivor/reject logic (`:149-168`) and the `validate` calls (`:153`, `:160`) are not touched. The validator still runs on the final decoded pixels (P5).
- **Everything outside `app.py` and `tests/`:** `validator.py`, `qrbuild.py`, `README.md` (no Space variables added), `.github/`, `requirements*.txt`, `docs/`, `local/` and `loop/`.

## 2. Behaviour table

Everything runs on CPU, with no model downloads and no GPU. `VAR` means `"QRAF_VAE_SLICING"`.
- In rows 1–9, `env` is passed explicitly unless the row says otherwise.
- Rows 10–15 use the existing fakes (`tests/test_vae_slicing.py:71-119`) and call `app._load_pipes()` directly. They must not set or leave behind `app._pipes`.

| # | Input | Observable result |
|---|---|---|
| 1 | `app.vae_slicing_enabled("cuda", {})` | `True` |
| 2 | `app.vae_slicing_enabled("cuda", {VAR: "1"})` | `True` |
| 3 | `app.vae_slicing_enabled("cuda", {VAR: "0"})` | `False` |
| 4 | `app.vae_slicing_enabled("cpu", e)` for each e in `{}`, `{VAR: "1"}`, `{VAR: "0"}` | `False` for each |
| 5 | `app.vae_slicing_enabled("cuda", {VAR: v})` for each v in `""`, `"true"`, `"false"`, `"off"`, `"no"`, `" 0"`, `"0 "`, `"00"`, `"2"` | `True` for each (only the exact `"0"` disables) |
| 6 | `monkeypatch.delenv(VAR, raising=False)`, then `app.vae_slicing_enabled("cuda")` with no `env` | `True` |
| 7 | `monkeypatch.setenv(VAR, "0")` **after** `import app`, then `app.vae_slicing_enabled("cuda")` with no `env` | `False`, which shows the value is read at call time |
| 8 | `monkeypatch.setenv(VAR, "1")`, then `app.vae_slicing_enabled("cpu")` with no `env` | `False` |
| 9 | `app.vae_slicing_enabled("cuda", {})` called twice | `True` both times, and `os.environ` is unchanged afterwards |
| 10 | fakes; `is_available → True`; VAR unset; `app._load_pipes()` | the fake txt2img `enable_vae_slicing` is called **exactly once**; the result is a dict with keys exactly `{"gen", "rescue"}` |
| 11 | fakes; `is_available → True`; VAR `"1"` | `enable_vae_slicing` is called exactly once |
| 12 | fakes; `is_available → True`; VAR `"0"` | `enable_vae_slicing` is called **zero** times |
| 13 | fakes; `is_available → False`; VAR unset | `enable_vae_slicing` is called zero times |
| 14 | fakes; `is_available → True`; VAR unset | the img2img fake was built with a `vae` kwarg that **is** the sentinel `VAE` (identity check); the img2img fake's own `enable_vae_slicing` is called zero times |
| 15 | row 10 compared with row 12 (VAR unset vs `"0"`) | `rec.calls` are equal apart from the slicing count. Both runs see `pipe.from_pretrained((app.BASE,), {controlnet, torch_dtype, safety_checker})` with `controlnet == "CN"` and `safety_checker is None`, plus `("pipe.to", ("cuda",), ())` and `("i2i.to", ("cuda",), ())` |
| 16 | `run_forge(PAY, "p", 3, 1.35, 25, 7, True, 1, pipes=fake)` with VAR `"0"`, then again with VAR unset (`HF_TOKEN` and `REJECTS_REPO` unset) | the reports are identical and contain `"1/3 passed"`; the last line is `"rejects not archived (HF_TOKEN/REJECTS_REPO unset)"`; the survivors are the same objects in the same order. The flag has no effect outside `_load_pipes` |
| 17 | `tests/test_loop.py::test_real_build_plan_queue_parses` run against the live `docs/04_Build_Plan.md`, with steps looked up by id | m2-6: done, `paths == ["app.py", "tests/"]`, `touches_gpu` false, scoped/ordinary, `gpu_env == {}`. m2-7: done, scoped/ordinary, `touches_gpu` true, `gpu_env == {"QRAF_VAE_SLICING": "1"}`. m2-7b: present, scoped/ordinary, `touches_gpu` true, `gpu_env == {"QRAF_VAE_SLICING": "0"}`, done state **not asserted**. m2-5: top/never-economize, `gpu_env == {}`, and it comes after m2-7b in queue order |
| 18 | full suite | everything else that is green on main stays green |

Expected red-on-main before the Implementer runs: rows 1, 5, 6, 9, 10 and 14 fail against today's helper (`app.py:43`). Rows 2, 3, 4, 7, 8, 11, 12, 13, 15 and 16 hold under both the old and the new rule and act as guards. Row 17 is red on main for an unrelated reason (§1 tests item 2) and is fixed by the Tester alone; it needs no Implementer change.

The orchestrator runs the real-generation check itself (`local\run_batch.py --seed 12345` ≥ 2/4, once with no extra env and once with `QRAF_VAE_SLICING=0`, per docs/06 §1a). No GPU test is specified here.

## 3. Editable paths
- **Implementer:** `app.py`, and only the body and docstring of `vae_slicing_enabled` (`app.py:39-43`).
- **Tester:** `tests/`, specifically `tests/test_vae_slicing.py` and `tests/test_loop.py`. Other tests must not be weakened.
- The Implementer may not touch `tests/`, `docs/`, `steps/`, `local/`, `loop/` or any other path.

## 4. Class and lane
- Class: **scoped**. Lane: **ordinary**.
- **Never-economize paths touched: none.** No `validator.py`, `qrbuild.py`, `README.md` (front-matter or otherwise) or `.github/`.
- The `app.py` hunk must sit inside `app.py:39-43`. It must not touch THE GATE line (`app.py:167`), the `run_forge`/`forge` spans (`app.py:135-186`) or any `validate` token. Any hunk there is a spec violation, and the step stops.
- No UI strings change, so there is no `ui-change` label.

## 5. Blocking questions
None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-7b/spec.md)
- Not certain:
  1. **Pre-existing red test, found by reading only.**
     - `tests/test_loop.py:138` expects the first three queue ids to be `["m2-6","m2-7","m2-5"]`, and `:141` expects m2-7 to be open.
     - The queue now reads m2-6 [x], m2-7 [x], m2-7b [ ] (`docs/04_Build_Plan.md:32-34`), and `loop/queue.py:75` sets `done` from `[x]`. So the test should be red since 6b1ec1e and fae5712. I did not run it.
     - If I'm wrong and it's green, row 17 is a harmless robustness rewrite. I put it in scope because otherwise "suite after commit" (06 §1a) would stop this step on a test the Implementer may not touch.
  2. **Only the exact `"0"` disables slicing.** This is a technical ruling that reads 03:18 literally and mirrors m2-7's exact-match style. It is listed here so Nimrod can overrule it. If he does, `"false"`, `"off"` or `"no"` would also disable, and that is a one-line change to the helper.
  3. **The GPU runs now test the right things, but the second one is slow.**
     - Run 1 (no env): `local/run_batch.py:42` wraps only on `"1"`, so this run exercises `app.py`'s own default-on path. That closes m2-7's Not certain 1.
     - Run 2 (`=0`): no slicing at all. 03:18 measured a 752 s forge (VRAM spill). With model load that should still fit inside `gpu_timeout_s = 1800` (`loop/config.toml:18`), but the margin is not measured.
     - The run-1 survivor md5 will no longer match the recorded `98bdaf02a516` (`docs/04_Build_Plan.md:29`), because slicing changes pixels by ≤ 2/255. The `=0` run should still reproduce it. Neither is a gate.
  4. **The Space changes behaviour once main mirrors.** ZeroGPU is CUDA, so the Space will decode with slicing from the next rebuild. The validator gates the final pixels, so the gate is unaffected. No Space variables are touched.
  5. **`local/run_batch.py` docstring is out of date.** Its docstring (`:13-14`) and wrapper still describe `=1` as opt-in. With `=1` set, slicing is enabled twice, which is harmless. `local/` is git-ignored and outside every editable path, so tidying it is a PC-side chore for the planner or Nimrod.
- Deploy: none
