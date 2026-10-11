Class: top · Step: m2-9

# m2-9: Reference image — IP-Adapter style reference under Advanced (OD 8, P6)

Sources:
- `docs/05_Open_Discussion.md:12`: "IP-Adapter style reference first (≈2.5 GB encoder, ~0.5 GB VRAM, +10–15 % time) … Needs P5 or batch 2 on the 4070." P5 is on by default (`docs/03_Decisions.md:18`, `app.py:39-43`).
- `docs/03_Decisions.md:19` (P6): "used for the run and discarded, never stored — not in the reject archive, no hash. The archive JSON records `reference: true|false` only. Disclosure line unchanged."
- Queue entry: `docs/04_Build_Plan.md:35`, which requires that "default generation without a reference stays byte-identical".

## 1. Scope

### What changes in `app.py` (Implementer)

1. **New module constants**, placed next to `CN` (`app.py:17`):
   - `IPA_REPO = "h94/IP-Adapter"`
   - `IPA_SUBFOLDER = "models"`
   - `IPA_WEIGHT = "ip-adapter_sd15.bin"`
   - `REF_SCALE = 0.5`, the default reference strength. This is a technical ruling and Nimrod can overrule it.

   The image encoder comes from `h94/IP-Adapter/models/image_encoder` (ViT-H, ≈2.5 GB, which matches OD 8). That is diffusers' default `image_encoder_folder`.

2. **Real closures in `_load_pipes` (`app.py:46-75`).** Today `gen` is at `:62-67` and `rescue` is at `:69-73`.
   - **Signatures.** Each closure gets two new keywords, `reference=None` and `reference_scale=REF_SCALE`, placed after `negative=NEG`.
   - **Lazy loading.** `_load_pipes` itself never loads the adapter. No encoder download happens at startup.
   - **One piece of closure state.** A single boolean (for example `nonlocal ip_loaded`) records whether the adapter is currently loaded. Nothing else is kept between calls, and the reference image is never stored in closure, module or global state.
   - **When `reference is not None`:**
     1. If the adapter isn't loaded, call `pipe.load_ip_adapter(IPA_REPO, subfolder=IPA_SUBFOLDER, weight_name=IPA_WEIGHT)` once. Then set `i2i.image_encoder = pipe.image_encoder` and `i2i.feature_extractor = pipe.feature_extractor`. `i2i` was built from `pipe.components` before the encoder existed (`app.py:56`). It shares the UNet but not the encoder.
     2. Call `pipe.set_ip_adapter_scale(float(reference_scale))`.
     3. Call the pipeline with the same kwargs as today, plus `ip_adapter_image=reference`. `gen` calls `pipe` and `rescue` calls `i2i`.
   - **When `reference is None`:**
     1. If the adapter is loaded, call `pipe.unload_ip_adapter()` once and set `i2i.image_encoder = None`. Then mark it as not loaded.
     2. Call the pipeline with **exactly** today's kwargs: no `ip_adapter_image` key and no `set_ip_adapter_scale` call.

     Unloading restores the default attention processors (`diffusers/loaders/ip_adapter.py:333-344`, as installed). That is what keeps the default path byte-identical, even after an earlier run in the same process used a reference.
   - The rest of `_load_pipes` stays the same: device and dtype, model loads, `.to(device)`, the P5 slicing call site (`:59-60`), and the return dict keys `{"gen", "rescue"}`.

3. **`run_forge` (`app.py:135-177`) gets two keyword parameters after `negative`:** `reference=None` (a PIL image or `None`) and `reference_scale: float = REF_SCALE`. All existing positional and keyword calls keep working.
   - **No reference.** `pipes["gen"]` and `pipes["rescue"]` are called exactly as today. Their kwargs are exactly `{"negative"}`, which keeps `tests/test_negative.py:92` green.
   - **With a reference.** Both calls also get `reference=<the same object, identity, not converted or copied>` and `reference_scale=float(reference_scale)`. The positional args don't change.
   - **Archive.** The call at `:176` becomes `build_reject_records(payload, settings, rejects, reference=reference is not None)`.
   - **Things that stay the same:** `settings` (`:174-175`) keeps exactly its 7 keys, the report header and lines (the reference is not echoed), the gate, and the rescue eligibility.
   - **No retention.** `run_forge` keeps no reference to the image after it returns.

4. **`build_reject_records` (`app.py:87-100`) gets a new keyword-only parameter `reference: bool = False`.**
   - Each `meta` gets one new top-level key, `"reference": bool(reference)`.
   - It goes at top level rather than inside `settings`, because `tests/test_negative.py:112-113` pins the `settings` keys.
   - Nothing else derived from the reference goes in. That means no pixels, hash, size, mode or filename.
   - The PNG bytes are still the candidate's own pixels.

5. **`forge` (`app.py:180-186`)** gets `reference=None, reference_scale=REF_SCALE` between `negative=""` and `progress`. It forwards them as `run_forge(..., negative=negative, reference=reference, reference_scale=reference_scale)`. The `@GPU(duration=120)` decorator and the `PayloadError` handling don't change.

6. **UI (`build_ui`, `app.py:190-220`).**
   - Inside `gr.Accordion("Advanced", open=False)` (`:200`), after `negative_box` (`:206-207`) and before `rescue` (`:208`), add:
     - `reference_img = gr.Image(label="Style reference image (optional)", type="pil", sources=["upload"], height=160)`
     - `reference_strength = gr.Slider(0.0, 1.0, value=REF_SCALE, step=0.05, label="Reference strength")`
   - `go.click` inputs (`:216`) become `[payload, prompt, batch, weight, steps, cfg, rescue, seed, negative_box, reference_img, reference_strength]`. The outputs don't change.
   - `gr.Blocks(title="QR Art Forge")` (`:191`) gets `delete_cache=(3600, 3600)`. Gradio writes uploads to its temp cache, and this setting ages them out after one hour and wipes them on restart (`gradio/blocks.py:1083`). That is P6 "discarded" on the server side. It's a technical ruling, listed so Nimrod can overrule it.
   - The labels are UI wording. Per docs/06 §4 they proceed on this default and are flagged in the PR body, with the `ui-change` label.

### What changes in `tests/` (Tester)
- Add a new test module for the rows below.
- **Update `tests/test_negative.py::test_forge_click_inputs_end_with_negative` (`:164-179`).** It asserts `len(ins) == 9` (`:171`), which this spec supersedes. It must now assert 11 inputs: `ins[8]` is the negative box, `ins[9]` is the reference Image, `ins[10]` is the strength Slider, and inputs 1–8 are unchanged. This replaces a superseded assertion and does not weaken the test.
- No other existing assertion may be relaxed.

### What does not change
- **The gate:** THE GATE line (`app.py:167-168`), the survivor/reject logic (`:149-168`), and the `validate` calls (`:153`, `:160`).
- **The disclosure line** (`app.py:211`). P6 says "Disclosure line unchanged."
- **Defaults and wiring:** `NEG`, `build_negative`, `vae_slicing_enabled`, `make_scheduler`, `get_pipes`, `archive_rejects`, and the defaults of every existing Advanced control.
- **Everything outside `app.py` and `tests/`:** `validator.py`, `qrbuild.py`, `README.md`, `.github/`, `requirements*.txt` (diffusers 0.30.3 already ships `IPAdapterMixin`, and transformers is already pinned), `docs/`, `local/` and `loop/`.

## 2. Behaviour table

Everything runs on CPU with no downloads. In rows 1–13, `pipes` is a recording fake, as in `tests/test_negative.py:21-31`. In rows 14–22, `_load_pipes()` runs against fakes installed by monkeypatching `diffusers.ControlNetModel`, `diffusers.StableDiffusionControlNetPipeline`, `diffusers.StableDiffusionControlNetImg2ImgPipeline`, `torch.cuda.is_available` (→ False) and `app.make_scheduler`, in the style of `tests/test_vae_slicing.py:76-124`. In those fakes:
- `FakePipe` and `FakeI2I` each record `__call__` kwargs and return an object with `.images`.
- `FakePipe` additionally records `load_ip_adapter`, `set_ip_adapter_scale` and `unload_ip_adapter`.
- The fake `load_ip_adapter` sets `self.image_encoder` to a sentinel `ENC`. The fake `unload_ip_adapter` sets it to `None`.
- Both fakes start with `image_encoder = None` and `feature_extractor = FE`, where `FE` is a sentinel.
- The tests must not populate `app._pipes`.

`R` is a small PIL image.

| # | Input | Observable result |
|---|---|---|
| 1 | `run_forge(PAY,"p",1,1.35,25,7,False,1,pipes=fake)` (no reference) | gen kwargs keys exactly `{"negative"}` |
| 2 | same with `reference=R` | gen kwargs `reference is R`, `reference_scale == 0.5` (`app.REF_SCALE`), `negative == app.NEG`; positional args identical to row 1 |
| 3 | same with `reference=R, reference_scale=0.8` | gen kwargs `reference_scale == 0.8` and is a `float` |
| 4 | `reference=R`, rescue on, `app.validate` patched so the gen image is a near-miss (as `tests/test_negative.py:70-81`) | rescue called once; rescue kwargs `reference is R`, `reference_scale` equals gen's |
| 5 | row 4 setup without a reference | rescue kwargs keys exactly `{"negative"}` |
| 6 | `reference=R`, gen returns `[GOOD, BAD, BAD]` | `len(surv)==1`, `"1/3 passed"` in report, last line is the archive line, report text identical to the same run without a reference |
| 7 | `reference=R`, `archive_rejects` captured | every record's `meta["reference"] is True`; `set(meta["settings"])` is exactly the 7 keys of `tests/test_negative.py:112-113` |
| 8 | no reference, `archive_rejects` captured | every record's `meta["reference"] is False` |
| 9 | row 7 | each meta has keys exactly `{"run_id","label","payload","settings","pass","score","max","results","reference"}`; `json.dumps(meta)` contains neither a hash of `R`'s bytes nor `R`'s `size` as a pair; PNG bytes decode to the candidate's size |
| 10 | `app.build_reject_records(PAY, SETTINGS, entries, now=NOW)` (reference omitted) | `meta["reference"] is False`; other fields as `tests/test_rejects.py:33-45` |
| 11 | `reference=R` with non-retaining fakes; `wr = weakref.ref(R)`; `del R`; `gc.collect()` | `wr() is None` (app keeps nothing) |
| 12 | `app.forge(PAY,"p",1,1.35,25,7,False,1,"n",R,0.7)` with `app.run_forge` captured | kwargs `negative=="n"`, `reference is R`, `reference_scale==0.7` |
| 13 | `app.forge(PAY,"p",1,1.35,25,7,False,1)` captured | kwargs `reference is None`, `reference_scale == app.REF_SCALE` |
| 14 | fakes; `app._load_pipes()` only | `load_ip_adapter` never called; result keys `{"gen","rescue"}` |
| 15 | fakes; `gen("p", C, 2, 1.35, 25, 7, 1)` | FakePipe call kwargs keys exactly `{"prompt","negative_prompt","image","num_images_per_prompt","controlnet_conditioning_scale","num_inference_steps","guidance_scale","generator","width","height"}`; no load/scale/unload calls |
| 16 | fakes; `rescue("p", I, C, 1.35, 25, 7, 1)` | FakeI2I call kwargs keys exactly `{"prompt","negative_prompt","image","control_image","strength","controlnet_conditioning_scale","num_inference_steps","guidance_scale","generator"}` |
| 17 | fakes; `gen(..., reference=R, reference_scale=0.6)` | `load_ip_adapter` called once with `("h94/IP-Adapter",)`, `subfolder="models"`, `weight_name="ip-adapter_sd15.bin"`; `set_ip_adapter_scale(0.6)`; pipe kwargs = row-15 set plus `ip_adapter_image`, which `is R` |
| 18 | row 17 then `rescue(..., reference=R, reference_scale=0.6)` | no second `load_ip_adapter`; `set_ip_adapter_scale(0.6)` again; i2i kwargs = row-16 set plus `ip_adapter_image is R`; `i2i.image_encoder is ENC` and `i2i.feature_extractor is pipe.feature_extractor` |
| 19 | row 17 then `gen(...)` with no reference | `unload_ip_adapter` called exactly once, before the pipe call; pipe kwargs exactly the row-15 set; `i2i.image_encoder is None` |
| 20 | row 19 then `gen(...)` with no reference again | no further unload; no load |
| 21 | `gen(reference=R)`, `gen(reference=R)` | `load_ip_adapter` called once in total |
| 22 | row 17 with non-retaining fakes, then weakref/`del`/`gc` on `R` | `wr() is None` (closures keep no image) |
| 23 | `app.build_ui()` | exactly one `gr.Image` labelled `"Style reference image (optional)"`, `type == "pil"`; exactly one `gr.Slider` labelled `"Reference strength"` with `value == 0.5`, `minimum == 0`, `maximum == 1`, `step == 0.05`; both descendants of the `"Advanced"` Accordion |
| 24 | `app.build_ui()` | Forge click has 11 inputs: 1–8 as `tests/test_negative.py:173-177`, 9 the negative box, 10 the reference Image, 11 the strength Slider; `get_api_info()` does not raise |
| 25 | `app.build_ui().delete_cache` | `== (3600, 3600)` |
| 26 | `app.build_ui()` Markdown values | `"Failed generations may be stored privately to improve quality."` present exactly once, unchanged |
| 27 | full suite | everything green on main stays green (with the row-24 update to `tests/test_negative.py`) |

Expected red on main: rows 2–4, 7–9 (key `reference`), 10, 12–13, 17–19, 21, 23–25. Rows 1, 5, 6, 11, 14–16, 20, 26 are guards. Row 22 is a guard on main only trivially (no `reference` keyword → TypeError; Tester may mark it red).

The orchestrator runs the real-generation check (`local\run_batch.py --seed 12345`, ≥ 2/4). `run_batch.py` passes no reference (`local/run_batch.py:88-89`), so it exercises rows 15/16 on the real closures. No GPU test is specified here.

## 3. Editable paths
- **Implementer:** `app.py`.
- **Tester:** `tests/`. That means the new module plus the row-24 update to `tests/test_negative.py:164-179`. No other existing test may be weakened.
- The Implementer may not touch `tests/`, `docs/`, `steps/`, `local/`, `loop/` or any other path.

## 4. Class and lane
- Class: **scoped**. Lane: **ordinary**.
- **Never-economize paths touched: none.** There are no changes to `validator.py`, `qrbuild.py`, `README.md` or `.github/`.
- The diff touches `run_forge` and `forge`. It must not change THE GATE line (`app.py:167-168`), the survivor filter around it, or any `validate` token (`:153`, `:160`). A hunk there is a spec violation, and the orchestrator must stop.
- UI strings are added, so the PR gets the `ui-change` label and a body flag.

## 5. Blocking questions
None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-9/spec.md)
- Not certain:
  1. **The GPU behaviour of the reference path is unverified.** The orchestrator's batch never passes a reference. Nothing automated checks these:
     - that `StableDiffusionControlNetImg2ImgPipeline` in diffusers 0.30.3 accepts `ip_adapter_image` when the encoder is assigned by attribute;
     - the pass rate with a reference at scale 0.5;
     - the +10–15 % time claim from OD 8.

     The planner or Nimrod should run one hand batch with a reference on the 4070.
  2. **Byte-identity is enforced structurally, not measured.** Rows 15/16/19 check structure only. They don't compare against a recorded md5. The md5 recorded at `docs/04_Build_Plan.md:29` predates P5 (see `steps/m2-7b/spec.md` Not certain 3). A main-vs-branch md5 comparison from `run_batch.py` would confirm it, but it isn't a gate.
  3. **The first reference run on ZeroGPU downloads the ≈2.5 GB encoder inside the `@GPU(duration=120)` slot.** That may time out the first reference run on the Space (OD 7). Changing the duration or preloading is out of scope.
  4. **`delete_cache=(3600, 3600)` also ages out gallery and control-image temp files after an hour.** This is my reading of P6 "discarded" as covering Gradio's upload cache. If Nimrod reads P6 as covering only the archive, drop the change and row 25.
  5. **`REF_SCALE = 0.5` and the UI labels are defaults pending Nimrod.** IP-Adapter scale trades style against scannability, and that trade hasn't been measured.
- Deploy: none
