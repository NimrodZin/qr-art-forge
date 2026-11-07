Class: top · Step: m2-9b

# m2-9b: Reference image errors show a clear re-upload message

Sources:
- Queue entry: `docs/04_Build_Plan.md:40`.
- Finding: `docs/04_Build_Plan.md:30`: "AVIF upload and hour-old upload (purged by delete_cache) raise raw errors → m2-9b."
- P6, reference never stored: `docs/03_Decisions.md:19`.

## 1. Scope

### Where the errors come from

Both errors are raised before `forge` runs, so nothing in `forge` or `run_forge` can catch them.

- **The call path.** `Blocks.process_api` calls `preprocess_data` first (`gradio/blocks.py:2187`), which calls `block.preprocess` (`gradio/blocks.py:1849`). For this component that reaches `image_utils.preprocess_image`, which calls `PIL.Image.open(file_path)` (`gradio/image_utils.py:298`).
- **AVIF.** Pillow 10.4.0 is pinned (`requirements.txt:12`, `requirements-ci.txt:7`) and the installed copy has no AVIF plugin. `Image.open` raises `PIL.UnidentifiedImageError`, an `OSError` subclass (`PIL/__init__.py:77`).
- **Purged upload.** The file is gone (`app.py:228` sets `delete_cache`), but the steps before preprocess let it through:
  - `_check_allowed` only compares paths and doesn't check the file exists (`gradio/processing_utils.py:478-510`, `gradio/utils.py:1579-1597`).
  - `async_move_resource_to_block_cache` keeps a path that is inside the cache as it is (`gradio/blocks.py:347-359`).

  `Image.open` then raises `FileNotFoundError`.
- **What the user sees today.** A non-`gr.Error` exception is sent with `error: None` unless `show_error` is set (`gradio/utils.py:1504-1517`, `gradio/queueing.py:774-788`). A `gr.Error` always shows its message.

### What changes in `app.py` (Implementer)

There are exactly three edits. The spec names their placement because the ordinary lane stops on any gate hit (section 4).

1. **New constant**, directly after `REF_SCALE` (`app.py:21`):
   ```python
   REF_ERROR = ("Couldn't read the style reference image. It may be a format we can't open "
                "(such as AVIF) or an upload that has expired. Please re-upload it as a PNG "
                "or JPG, or clear it to forge without a reference.")
   ```
   This is UI wording. It proceeds on this default and is flagged in the PR body (`docs/06_Loop_Spec.md:48`).

2. **New helper**, inserted after the `# --- UI` comment (`app.py:226`) and before `def build_ui` (`app.py:227`):
   ```python
   def reference_preprocess(original):
       """Wrap gr.Image.preprocess: an upload Pillow cannot read, or one delete_cache has purged, becomes REF_ERROR."""
       def preprocess(payload):
           try:
               return original(payload)
           except (OSError, SyntaxError, Image.DecompressionBombError):
               raise gr.Error(REF_ERROR, print_exception=False) from None
       return preprocess
   ```
   - **`OSError`** covers `UnidentifiedImageError`, `FileNotFoundError` and truncated files.
   - **`SyntaxError`** covers Pillow's "broken PNG file", which can surface while the pixels load in `im.convert` (`gradio/image_utils.py:313`). This is from my memory of the Pillow source, not traced (see Not certain 3).
   - **`DecompressionBombError`** is a plain `Exception` subclass (`PIL/Image.py:84`), so it needs its own entry.
   - **`ValueError` must not be caught.** `gr.Error` is a `ValueError` (`gradio_client/exceptions.py:19`). Gradio's own SVG message (`gradio/image_utils.py:296`) has to pass through unchanged, and so does `"Image path is None."` (`gradio/image_utils.py:281`), which is not an upload problem.
   - **`print_exception=False` and `from None`** keep the upload's path and filename out of the server log. Pillow's and the OS's messages both contain the path. This is in the spirit of P6 (`docs/03_Decisions.md:19`): nothing derived from the reference is kept.

3. **One new line in `build_ui`**, directly after the `gr.Image(...)` call ends (`app.py:245-246`) and before `reference_strength`:
   ```python
   reference_img.preprocess = reference_preprocess(reference_img.preprocess)
   ```

### Why an instance wrapper and not a `gr.Image` subclass

This is a technical ruling.

- `tests/test_reference.py:526` pins `type(c)` to exactly `gr.Image`, and that assertion must not be relaxed.
- A subclass also changes `get_block_name()` unless it sets `is_template` (`gradio/blocks.py:253-263`), and that name selects the frontend component.
- The wrapper survives normal use:
  - `SessionState` shares the same Block objects (`gradio/state_holder.py:66`, `gradio/blocks.py:976-981`, `gradio/state_holder.py:83-90`).
  - `reference_img` is not an event output (`app.py:259`), so it isn't rebuilt from a `gr.update`.
  - `get_config` reads only constructor parameters (`gradio/blocks.py:289-297`), so the frontend config doesn't change.

### What changes in `tests/` (Tester)

- Add a new module, `tests/test_reference_errors.py`, for the rows below.
- No existing test changes. All of `tests/test_reference.py` and `tests/test_negative.py` must stay green as they are.

### What does not change

- **`run_forge` (`app.py:166-212`), `forge` (`app.py:215-223`), the gate and the validator import (`app.py:14`).** The diff must not touch them.
- **Generation.** `_load_pipes`, `NEG`, `build_reject_records`, `archive_rejects` and the archive schema don't change.
- **Default generation.** No reference gives `payload=None`, which still returns `None` (`gradio/image_utils.py:271-272`). `local/run_batch.py:88` calls `run_forge` directly and never goes through this wrapper. Default generation is byte-identical because no code on its path changes.
- **Other UI.** The `gr.Image` arguments (`app.py:245-246`), `delete_cache` (`app.py:228`), the disclosure line (`app.py:252`), and all other labels and defaults.
- **Formats.** No AVIF plugin is added and `requirements*.txt` doesn't change. AVIF stays unsupported and now has a clear message.
- **Everything outside `app.py` and `tests/`.**

## 2. Behaviour table

Everything runs on CPU with no downloads and no pipelines loaded.

**Fixtures:**
- `REF` is the reference block. It is found by `(btn,) = Forge button; (dep,) = the click fn; REF = dep.inputs[9]`, as in `tests/test_reference.py:515-517`. Use the original wrapped method, not a fresh `gr.Image`.
- `PAYLOAD(path, name)` is `{"path": str(path), "orig_name": name, "meta": {"_type": "gradio.FileData"}}`. The `meta` is required (`gradio/data_classes.py:252-257`).
- `AVIF_BYTES` is `b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 64`, written to `tmp_path/"ref.avif"`. Pillow 10.4.0 cannot identify it.
- `PNG` and `JPG` are real files saved by Pillow, 37×23, mode RGB. `PURGED` is a path in `tmp_path` that doesn't exist.
- `INPUTS(ref)` is the 11-item list `["example.com", "p", 1, 1.35, 25, 7, False, 1, "", ref, 0.5]`.

| # | Input | Observable result |
|---|---|---|
| 1 | `REF.preprocess(ImageData(**PAYLOAD(avif, "ref.avif")))` | raises `gr.Error`; `.message == app.REF_ERROR` |
| 2 | `REF.preprocess(ImageData(**PAYLOAD(PURGED, "ref.png")))` | raises `gr.Error`; `.message == app.REF_ERROR` |
| 3 | PNG file truncated to its first 40 bytes, through `REF.preprocess` | raises `gr.Error`; `.message == app.REF_ERROR` |
| 4 | Valid PNG with `monkeypatch.setattr(PIL.Image, "MAX_IMAGE_PIXELS", 100)` (37×23 is above 2×100, `PIL/Image.py:3354-3365`) | raises `gr.Error`; `.message == app.REF_ERROR` |
| 5 | Rows 1 and 2, the caught exception | `.print_exception is False`; `.message` contains neither `"ref.avif"` nor `str(tmp_path)` |
| 6 | `app.REF_ERROR` | contains `"re-upload"`, `"PNG"` and `"JPG"` |
| 7 | `asyncio.run(demo.preprocess_data(dep, INPUTS(PAYLOAD(avif, "ref.avif")), None))` (the real Gradio path) | raises `gr.Error` with `.message == app.REF_ERROR` |
| 8 | Same as row 7 with `PAYLOAD(PURGED, "ref.png")` | raises `gr.Error` with `.message == app.REF_ERROR` |
| 9 | `gradio.utils.error_payload(err, False)` on the error from row 7 | `content["error"] == app.REF_ERROR` (shown even when `show_error` is off) |
| 10 | `app.run_forge` replaced by a recorder; `asyncio.run(demo.process_api(dep, INPUTS(PAYLOAD(avif, "ref.avif")), state=SessionState(demo)))` | raises `gr.Error`; the recorder was never called (no generation and no GPU slot) |
| 11 | Same as row 10 with `PAYLOAD(PURGED, "ref.png")` | raises `gr.Error`; the recorder was never called |
| 12 | `REF.preprocess(None)` | returns `None` |
| 13 | `asyncio.run(demo.preprocess_data(dep, INPUTS(None), None))` | item `[9]` is `None`; item `[10] == 0.5` |
| 14 | `REF.preprocess` with the valid PNG, and with the valid JPG | returns a `PIL.Image.Image`, mode `"RGB"`, size `(37, 23)` |
| 15 | Row 14 PNG, pixels compared with an unwrapped `gr.Image(type="pil").preprocess` on the same file | `tobytes()` identical |
| 16 | `asyncio.run(demo.preprocess_data(dep, INPUTS(PAYLOAD(png, "ref.png")), None))` | item `[9]` is a `PIL.Image.Image`, size `(37, 23)` |
| 17 | `.svg` file with `orig_name="x.svg"` through `REF.preprocess` | raises `gr.Error`; `.message` is Gradio's `"SVG files are not supported as input images for this app."`, not `REF_ERROR` |
| 18 | `ImageData(path=None)` through `REF.preprocess` | raises `ValueError` with `"Image path is None."`; not `REF_ERROR` |
| 19 | `app.reference_preprocess(lambda p: (_ for _ in ()).throw(RuntimeError("x")))(None)` | `RuntimeError` propagates unchanged |
| 20 | Row 14 PNG result: `wr = weakref.ref(im)`; `del im`; `gc.collect()` | `wr() is None` (the wrapper keeps no image) |
| 21 | `app.build_ui()` | `type(REF) is gr.Image`; `REF.get_block_name() == "image"`; `REF.type == "pil"`; `demo.get_api_info()` does not raise |
| 22 | `REF.get_config()` compared with a plain `gr.Image` built with the same constructor arguments | the keys `"type"`, `"sources"`, `"label"`, `"height"` and `"image_mode"` are equal |
| 23 | Full suite | everything green on main stays green |

Expected red on main: rows 1–11 and 19. Rows 12–18 and 20–22 are guards, and any guard that references `app.reference_preprocess` or `app.REF_ERROR` may be red on main for that reason. Row 18 must construct `ImageData` directly, because `FileData` needs a path.

The orchestrator runs the real-generation check (`local\run_batch.py --seed 12345`, ≥ 2/4). No GPU test is specified here.

## 3. Editable paths

- **Implementer:** `app.py`.
- **Tester:** `tests/` (new module only).
- The Implementer may not touch `tests/`, `docs/` or `steps/`, or any other path.

## 4. Class and lane

- Class: **scoped**. Lane: **ordinary**.
- **Never-economize paths touched: none.** That covers `validator.py`, `qrbuild.py`, `README.md` and `.github/`. The THE GATE line (`app.py:201`) is untouched.
- **The orchestrator must see no gate hit.** `touched_never_economize` (`loop/gates.py:135-169`) would stop this ordinary step on any of the following:
  - a hunk overlapping `run_forge` or `forge` (`loop/config.toml:49`), including decorators;
  - a hunk overlapping the validator import (`app.py:14`);
  - a hunk overlapping lines within 3 of THE GATE;
  - any changed line, comment or docstring containing the whole word `validate`, or the text `THE GATE` or `DISCLOSURE`.

  The three placements in section 1 clear all of these. New code must not use those words. Inserting the helper directly after `app.py:223` would be a hit, so it goes after the UI comment at `app.py:226`.
- **UI strings:** the error message is new user-visible wording. The changed-line UI scan looks for `label=`, `placeholder=` or `gr.Markdown(` (`loop/gates.py:19`), and this diff has none of those, so it won't trip automatically. The Implementer must flag `REF_ERROR` in its handover, and the PR needs the `ui-change` label and a body flag (`docs/06_Loop_Spec.md:49`).

## 5. Blocking questions

None

## Handover

- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-9b/spec.md)
- Not certain:
  1. **Nothing here has been run.** The failure paths come from reading the installed Gradio 5.50.0 and Pillow 10.4.0 sources. The `FileNotFoundError` path is traced with cache-internal and missing paths in mind, but it wasn't reproduced against a live hourly purge. A manual check on the PC (upload AVIF, then remove an uploaded file from the Gradio cache and press Forge) would confirm the modal appears in the browser. Rows 7–11 are the closest automated stand-in.
  2. **`demo.process_api` outside a server (rows 10–11).** I expect it to raise during preprocess before anything server-specific runs (`gradio/blocks.py:2136-2141`, `:2187`), but I did not read every line between those two. If it fails for an unrelated reason in the test context, the Tester may report it and fall back to row 7's `preprocess_data` plus a recorder check.
  3. **Which corrupt-file exception appears when.** The `SyntaxError` from a broken PNG during load is from memory of Pillow's PNG plugin, not traced in the installed source. Row 3's truncated file may raise `UnidentifiedImageError` rather than a load-time error. Either way it maps to `REF_ERROR`, and `SyntaxError` is in the tuple as a precaution. A file that fails with another exception type would still show a raw error.
  4. **Instance-attribute override of `preprocess`.** This relies on Gradio calling `block.preprocess` through the instance (`gradio/blocks.py:1849`), which holds in the pinned 5.50.0. A Gradio upgrade could change that. Rows 7, 8, 10 and 11 would catch it.
  5. **The message stays on the error modal for 10 seconds** (the default, `gradio/exceptions.py:76`). The failed upload also stays in the widget until the user clears or replaces it, and I left that behaviour alone. The wording of `REF_ERROR` is a default pending Nimrod.
- Deploy: none
