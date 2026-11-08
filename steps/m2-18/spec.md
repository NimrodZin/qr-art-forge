Class: top · Step: m2-18

# m2-18 · Default checkpoint Realistic Vision 5.1

Source: `docs/04_Build_Plan.md:45` (queue line), `docs/03_Decisions.md:6` (D1 v0.10).

## 1. Scope

**Changes: one string literal on one line.** `app.py:17` becomes:

```python
BASE = os.environ.get("BASE_MODEL", "SG161222/Realistic_Vision_V5.1_noVAE")
```

The default checkpoint becomes Realistic Vision 5.1. `BASE_MODEL` still overrides it through the same `os.environ.get` call, and `BASE_MODEL=Lykon/dreamshaper-8` restores DreamShaper 8. `app.py:62` already loads whatever `BASE` holds, so it needs no edit.

**Tests added** (Tester only): the rows marked new in §2, including the Realistic Vision scheduler check beside the existing DreamShaper one.

**Does not change:**
- `make_scheduler` (`app.py:41-44`) and its use (`app.py:63`).
- The ControlNet constant and its load (`app.py:18`, `app.py:60`).
- VAE slicing (`app.py:47-51`, `app.py:67-68`).
- The `gen` and `rescue` closures (`app.py:88-105`).
- IP-Adapter (`app.py:19-22`, `app.py:72-86`).
- `NEG` (`app.py:26-27`).
- `run_forge`, `forge`, THE GATE line (`app.py:170-227`, `app.py:205`).
- The reject archive schema (`app.py:119-135`).
- The UI, `styles.py`, `validator.py`, `qrbuild.py`, `README.md`, `requirements*.txt`, `docs/`.

Default generation changes by design, so there is no byte-identical check (`docs/04_Build_Plan.md:45`). `BASE_MODEL=""` keeps today's behaviour and is out of scope.

The Reviewer should confirm that the `app.py` diff is exactly this one line.

## 2. Behaviour table

| # | Input | Observable result | On main today |
|---|---|---|---|
| 1 | `BASE_MODEL` unset, fresh load of `app.py` | `BASE == "SG161222/Realistic_Vision_V5.1_noVAE"` | **red** (new) |
| 2 | `BASE_MODEL=Lykon/dreamshaper-8`, fresh load | `BASE == "Lykon/dreamshaper-8"` | green (new) |
| 3 | `BASE_MODEL=someone/other-sd15`, fresh load | `BASE == "someone/other-sd15"`, verbatim | green (new) |
| 4 | `BASE_MODEL` unset, `_load_pipes()` with fake diffusers classes | The pipeline's `from_pretrained` gets positional args exactly `("SG161222/Realistic_Vision_V5.1_noVAE",)`, keywords exactly `controlnet`, `torch_dtype`, `safety_checker`, and `safety_checker` is `None` | **red** (new) |
| 5 | `BASE_MODEL=Lykon/dreamshaper-8`, `_load_pipes()` with fakes | The pipeline's `from_pretrained` gets positional args exactly `("Lykon/dreamshaper-8",)` | green (new) |
| 6 | Rows 4 and 5 | `ControlNetModel.from_pretrained` gets `("monster-labs/control_v1p_sd15_qrcode_monster",)` and `subfolder="v2"` under both checkpoints | green (new) |
| 7 | `DPMSolverMultistepScheduler.load_config("SG161222/Realistic_Vision_V5.1_noVAE", subfolder="scheduler")` passed to `app.make_scheduler` (network, tiny file, same form as `tests/test_scheduler.py:7`) | `scheduler.config.algorithm_type == "dpmsolver++"` and `scheduler.config.use_karras_sigmas is True` | green (new) |
| 8 | Existing tests | `tests/test_scheduler.py:6-10` (DreamShaper) and all of `tests/test_vae_slicing.py` stay unmodified and green | green |

**Notes for the Tester:**
- `BASE` is read at import, so each fresh-load row needs its own execution of `app.py`.
- Use `importlib.util.spec_from_file_location` under a private module name. This leaves `sys.modules["app"]` and `app._pipes` untouched, because `tests/test_vae_slicing.py:127-132` asserts that cache is not populated.
- Set or delete `BASE_MODEL` with `monkeypatch` in every row, so a developer's shell cannot change the result.
- For rows 4-6, reuse the fake pattern in `tests/test_vae_slicing.py:76-124`, including the `make_scheduler` fake on the freshly loaded module.
- Rows 1 and 4 fail on main, which satisfies the driver's red check: it stops only when the Tester's files exit 0 (`loop/run.py:311-314`). The other new rows pin behaviour that must survive and are expected to pass on main.

The orchestrator runs the real-generation check, including the DreamShaper run from the queue line's `gpu_env` (`docs/06_Loop_Spec.md:22`). No GPU test is specified here.

## 3. Editable paths

- Implementer: `app.py`, line 17 only.
- Tester: `tests/`.

The Implementer may not touch `tests/`, `docs/` or `steps/`.

## 4. Class and lane

Class **scoped**, lane **ordinary**.

The step touches no never-economize path:
- `app.py:17` is outside the gate spans. Those are `run_forge` and `forge` (`app.py:170-227`), the validator import alone with no context lines (`app.py:15`, `loop/gates.py:132`), and ±3 lines around the THE GATE marker (`app.py:205`, `loop/gates.py:157`, `loop/config.toml:50-51`).
- The changed line has no `validate` token or gate marker (`loop/gates.py:159-161`), so the driver's gate check should not fire.
- The line carries no UI string (`loop/gates.py:19`), so no `ui-change` flag applies.

Any diff reaching those spans stops the step.

## 5. Blocking questions

None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-18/spec.md)
- Not certain:
  1. I could not read the Realistic Vision scheduler config. The Hugging Face tool was denied and no copy turned up at the default cache path. The indirect evidence is that the local batches loaded this checkpoint through `app.get_pipes()`, which calls `make_scheduler` (`local/sched_batch.py:226-230`, `local/styles_batch_v2.py:598-609`). If row 7 fails, that is stop and report, not fix.
  2. A merge to main pushes to the Space automatically (`.github/workflows/sync-to-hf.yml:3-4,11`), so the Space should switch checkpoint on merge. Two things are unknown: whether a `BASE_MODEL` Space secret (`README.md:26`) would override the new default, and how long the first Realistic Vision load takes inside the 120 s ZeroGPU window (`app.py:219`). All Realistic Vision measurements so far are from the PC. Nimrod should check the secret, since secrets are outside the loop.
  3. Two git-ignored scripts assume the app default is DreamShaper. `local/f1_batch.py:31` would, going by its comment, run Realistic Vision under its "dreamshaper" arm. `local/styles_batch_v2.py:595-604` would stop on its assert if rerun. Both are PC-side chores outside this step.
  4. The reject archive does not record which checkpoint produced a reject (`app.py:212-213`), so rejects from before and after the switch differ only by timestamp. This step does not change that, because any schema change touches persisted data and is Nimrod's decision.
- Deploy: none
