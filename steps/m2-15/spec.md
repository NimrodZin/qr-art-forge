Class: top · Step: m2-15

# m2-15: Style presets (OD 14, order B)

## 1. Scope

**New file `styles.py`.** It holds the table and two pure functions, and imports the standard library only.

```python
STYLE_NONE = "None"
STYLE_NEGATIVE = "text, letters, words, watermark, signature"
class Style(NamedTuple): prompt_suffix: str; negative_suffix: str; strength: float
STYLES = {"Mosaic": Style(...), "Stained glass": Style(...), "Rug": Style(...), "Embroidery": Style(...)}
STYLE_CHOICES = [STYLE_NONE, *STYLES]
def apply_style(name, prompt, negative) -> tuple   # (effective prompt, effective negative)
def style_strength(name) -> float | None           # reads STYLES at call time
```

Suffixes, verbatim from `docs/04_Build_Plan.md:41`:

| Style | Prompt suffix |
|---|---|
| Mosaic | `as an ancient Roman floor mosaic, small square marble and lapis tesserae, irregular grout, soft daylight, photographed from directly above` |
| Stained glass | `as a leaded stained glass window, coloured cathedral glass pieces joined by thin lead came, backlit by daylight, front view` |
| Rug | `woven into a hand-knotted wool rug, dense pile, natural dyes, geometric border, photographed from directly above` |
| Embroidery | `as hand embroidery on natural linen, french knots and satin stitch, colourful silk threads, macro photograph, front view` |

Every style has negative suffix `STYLE_NEGATIVE` and strength `1.35`.

**Four edits to `app.py`:**

1. **Import.** Add one line, `from styles import STYLE_CHOICES, STYLE_NONE, apply_style, style_strength`, immediately before `app.py:13`.
   - It must not go directly after `:13` or `:14`. `loop/gates.py:164-166` widens a pure insertion to (start, start+1), so either position overlaps the validator-import span (`loop/gates.py:132`, `app.py:14`) and stops the ordinary lane.
2. **Handlers.** Define both immediately after `app.py:240`, inside `build_ui()`, before `with gr.Blocks`:
   ```python
   def forge_with_style(payload, prompt, batch, weight, steps, cfg, rescue, seed, negative,
                        reference, reference_scale, style_name, progress=gr.Progress()):
       prompt, negative = apply_style(style_name, prompt, negative)
       return forge(payload, prompt, batch, weight, steps, cfg, rescue, seed, negative,
                    reference, reference_scale, progress=progress)

   def strength_for_style(style_name):
       strength = style_strength(style_name)
       return gr.skip() if strength is None else strength
   ```
   - `progress` must stay the parameter after the 12 inputs, because Gradio inserts it at its parameter index (`gradio/helpers.py:961-962`).
   - No nested def may be named `forge` or `run_forge`. `gate_spans` walks the whole tree (`loop/gates.py:127-129`), and `tests/test_loop.py:1257` expects exactly two multi-line spans.
3. **Dropdown.** Between `app.py:249` and `:250`, add `style = gr.Dropdown(choices=STYLE_CHOICES, value=STYLE_NONE, label="Style")`.
   - Keep `label=` literally on a line in `app.py`. It is what raises the `ui-change` flag (`loop/gates.py:19`, `:174-176`).
4. **Wiring.** Replace `app.py:271-273`, and add the change listener after it:
   ```python
   go.click(forge_with_style, [payload, prompt, batch, weight, steps, cfg, rescue, seed, negative_box,
                               reference_img, reference_strength, style],
            [gallery, report, ctrl], api_name="forge")
   style.change(strength_for_style, [style], [weight], queue=False, show_progress="hidden")
   ```
   - `api_name="forge"` keeps the endpoint name that `local/ui_test.py:20-21` calls. Without it the name would come from the handler (`gradio/blocks.py:761-776`).
   - Don't pass `api_name=False` or `show_api=False` on the change listener; both emit a DeprecationWarning (`gradio/blocks.py:726-741`).

**Semantics:**

- **Prompt.** A named style gives `prompt + ", " + suffix`, exactly as written, with no trimming.
- **Negative.** If the user negative is `None`, empty or whitespace-only, the style negative stands alone. Otherwise the result is `negative.strip() + ", " + style negative`. This matches how `build_negative` treats user text (`app.py:162-166`), which then prefixes the fixed `NEG` as it does today.
- **`None` style.** The string `"None"` and Python `None` both return `prompt` and `negative` as the same objects. Python `None` is included because the Dropdown passes a null payload straight through (`gradio/components/dropdown.py:194-195`).
- **Unknown name.** Raises `KeyError`. Through the UI the Dropdown rejects it first (`gradio/components/dropdown.py:205-208`).
- **Strength.** The style sets the slider only. `forge_with_style` always forwards the slider's value, so the user can still move it.

**What does not change:**

- `forge` and `run_forge` (`app.py:218-226`, `:169-215`)
- the validator import (`app.py:14`) and THE GATE line (`app.py:204`)
- `validator.py`, `qrbuild.py`, `README.md`, `.github/`, `docs/`, `requirements*.txt`
- the archive schema: `settings` keeps its keys (`app.py:211-212`) and its `prompt` field now holds the effective prompt, as the queue line orders (`docs/04_Build_Plan.md:41`)

No new line in `app.py` or `styles.py` may contain the token `validate` (`loop/gates.py:119`, `:159-161`).

No deploy config change is needed: the sync pushes the whole of main, so `styles.py` reaches the Space (`.github/workflows/sync-to-hf.yml:11`).

**Existing tests the Tester must update.** The Forge click goes from 11 to 12 inputs; style is appended last so that indices 0–10 stay put.

- `tests/test_negative.py:171`: expect 12, and `ins[11]` is the Style dropdown.
- `tests/test_reference.py:512-527`: expect 12 and add `(gr.Dropdown, "Style")` to the list. The test name says eleven, so rename it.
- `tests/test_reference_errors.py:33-34`: `make_inputs` appends `"None"`, because Gradio rejects too few inputs (`gradio/blocks.py:1773-1799`).

## 2. Behaviour table

In every row, `dep` is the Forge click dependency, found as in `tests/test_negative.py:168-169`. `dep.fn` is the raw handler (`gradio/blocks.py:820-821`), so tests can call it directly. `app.forge`, `app.run_forge` and `app.get_pipes` are reached by global name, so `monkeypatch` works on them. Generation is always mocked.

**`styles.py`**

| # | Input | Observable result |
|---|---|---|
| 1 | `styles.STYLE_CHOICES` | `["None", "Mosaic", "Stained glass", "Rug", "Embroidery"]`, in that order |
| 2 | `apply_style(name, "a cat", "")` for each of the 4 styles | prompt is `"a cat, " +` the exact suffix from §1 |
| 3 | each entry of `STYLES` | negative suffix is exactly `text, letters, words, watermark, signature`; strength is `1.35`, within the slider's 0.8–2.0 (`app.py:252`) |
| 4 | `apply_style("Mosaic", "a cat", "people")` | negative is `people, text, letters, words, watermark, signature` |
| 5 | `apply_style("Mosaic", "a cat", n)` for `n` in `""`, `None`, `"  \n\t "` | negative is `text, letters, words, watermark, signature` |
| 6 | `apply_style("Mosaic", "a cat", "  red  ")` | negative is `red, text, letters, words, watermark, signature` |
| 7 | `apply_style(s, p, n)` for `s` in `"None"`, `None`; `n` in `""`, `None`, `"  red  "`; `p` in `"a cat"`, `""` | returns `p` and `n` unchanged, as the same objects |
| 8 | `apply_style("Mosaic", "", "")` | prompt is `", as an ancient Roman floor mosaic, …"`, the literal formula with an empty prompt |
| 9 | `apply_style("Nope", "p", "")`, `style_strength("Nope")` | `KeyError` |
| 10 | `style_strength` | `"Mosaic"` gives `1.35`; `"None"` and `None` give `None`; with `STYLES["Mosaic"]` patched to strength 1.6 it gives `1.6` |
| 11 | parse `styles.py` with `ast` | imports the standard library only; the token `validate` does not appear |

**`forge_with_style`**

| # | Input | Observable result |
|---|---|---|
| 12 | `dep.inputs` and `dep.outputs` | 12 inputs: the 11 in the order of `tests/test_reference.py:519-525`, then `(gr.Dropdown, "Style")`; outputs are gallery, report, control, as today |
| 13 | `dep.tracks_progress`; signature of `dep.fn` | `True`; the last parameter is `progress`, with a `gr.Progress` default |
| 14 | `dep.fn(..., "None", progress=sentinel)` with `app.forge` recorded | `forge` receives the same 11 values positionally, and `progress is sentinel` by keyword |
| 15 | `dep.fn` with style `"None"`, `app.get_pipes` mocked and a callable `progress`, compared with a direct `app.run_forge(PAY, PROMPT, 4, 1.35, 25, 7, True, 12345, pipes=pipes)` | the `gen` calls are equal: prompt, control bytes, batch, weight, steps, cfg, seed; kwargs are exactly `{"negative"}` and the value is `app.NEG` |
| 16 | `dep.fn` with style `"Mosaic"` and user negative `"people"`, `app.forge` recorded | prompt and negative are effective; every other argument is unchanged |
| 17 | `dep.fn` with style `"Mosaic"` and slider 1.6, with and without the table patched to another strength | `forge` receives weight `1.6`; the style never overrides the slider |
| 18 | style `"Mosaic"`, user negative `""`, mocked pipes | `gen` receives the effective prompt and `app.NEG + ", text, letters, words, watermark, signature"` |
| 19 | style `"Mosaic"`, near-miss with rescue on, using the near-miss `validate` of `tests/test_negative.py:71-75` | `rescue` receives the same effective prompt and negative as `gen` |
| 20 | style `"Mosaic"` with a reference image and scale 0.7 | `gen` receives `reference` (same object) and `reference_scale` 0.7 |
| 21 | style `"Mosaic"`, `gen` returns `[GOOD, BAD, BAD]` (`tests/test_gate.py:9-10`) | exactly one survivor, `GOOD`; the report has `1/3 passed`; `BAD` is absent |
| 22 | style `"Mosaic"`, payload over 80 characters after normalisation | `gr.Error` with the `PayloadError` text (`app.py:225-226`); `gen` is not called |
| 23 | `app.forge` mocked to return a sentinel | `dep.fn` returns that same object |
| 24 | `demo.process_api` as in `tests/test_reference_errors.py:96-97`, 12 inputs, style `"Mosaic"`, `app.run_forge` recorded | `run_forge` receives the effective prompt and negative |
| 25 | same path with style `"Nope"` | `gr.Error` from the Dropdown; `run_forge` is not called |
| 26 | style `"Mosaic"`, rejects captured as in `tests/test_reference.py:74-78` | `settings["prompt"]` is the effective prompt; `set(settings)` and `set(meta)` equal `SETTINGS_KEYS` and `META_KEYS` (`tests/test_reference.py:21-23`) |

**Slider**

| # | Input | Observable result |
|---|---|---|
| 27 | dependencies with target `(style._id, "change")` | exactly one; inputs `[style]`, outputs `[QR strength slider]`, `queue` is `False` |
| 28 | its `fn("Mosaic")`, then with `STYLES["Mosaic"]` patched to strength 1.6 | `1.35`, then `1.6` |
| 29 | its `fn("None")`, `fn(None)` | `gr.skip()`, i.e. `{"__type__": "update"}` (`gradio/helpers.py:1114-1121`); the slider's built value stays `1.35` |

**UI and gate shape**

| # | Input | Observable result |
|---|---|---|
| 30 | `app.build_ui()` | exactly one `gr.Dropdown` labelled `Style`; value `"None"`; choice values as row 1; not multiselect; `allow_custom_value` is False |
| 31 | position of the dropdown | same parent as the `Image prompt` textbox; child order is prompt, Style, `Advanced` accordion; no `Advanced` ancestor |
| 32 | `demo.get_api_info()` | builds; `/forge` is in `named_endpoints` with 12 parameters |
| 33 | `inspect.signature(app.forge)`, `inspect.signature(app.run_forge)` | parameter names and defaults as at `app.py:219-220` and `:169-172`; `app.validate is validator.validate` |
| 34 | `loop.gates.gate_spans` on the working-tree `app.py`, with `gate_functions` from `loop/config.toml:49` | exactly two multi-line spans, plus the single-line validator import |

## 3. Editable paths

`styles.py`, `app.py`, `tests/`

The Tester writes `tests/` only. The Implementer writes `styles.py` and `app.py` only, and may not touch `tests/`, `docs/` or `steps/`.

## 4. Class and lane

Class **scoped**, lane **ordinary**.

The step touches no never-economize path. `validator.py`, `qrbuild.py`, `README.md` front-matter, `.github/` and the THE GATE line in `app.py` are all untouched. `app.py` is edited only at the import line in §1 and inside `build_ui()`.

If `touched_never_economize` still reports `app.py (gate)`, the ordinary lane stops (`docs/06_Loop_Spec.md:44`). The fix is to move the offending edit, never to change gate code.

This is a UI change: the PR gets `ui-change`, and the display names are provisional until Nimrod sees them (`docs/06_Loop_Spec.md:48-49`).

## 5. Blocking questions

None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-15/spec.md)
- Not certain:
  1. **ZeroGPU path unverified.** `forge` is now called from an undecorated handler. CI and the PC use the no-op `GPU` shim (`app.py:28-33`), so no CPU test covers a real ZeroGPU allocation or live progress through the handler. It needs one run on the Space.
  2. **No styled generation has been run.** The real-generation check calls `app.run_forge` directly (`local/run_batch.py:88-89`), so it never goes through the dropdown. Pass rates at 1.35 with these suffixes are unmeasured until the styles batch; the validator gate still drops whatever fails.
  3. **Long prompts may lose the suffix.** The suffix goes last, so a long user prompt could push it past CLIP's token limit, and that part of the style would be dropped. I did not count tokens.
  4. **My rulings beyond the queue line.**
     - An empty prompt with a style gives a leading `", "`.
     - A non-empty user negative is stripped.
     - Python `None` counts as the None style.
     - An unknown name raises `KeyError`.
     - The slider listener uses `queue=False` and `show_progress="hidden"`, and the Forge click keeps `api_name="forge"`.
  5. **Slider behaviour once strengths differ.** Going back to None leaves the slider where the last style put it, the literal reading of "strength untouched". Re-picking the same style doesn't fire `change`, so a moved slider stays put. Neither shows while every strength is 1.35.
  6. **UI scan coverage.** The choice names live in `styles.py`, which the UI scan doesn't read (`loop/gates.py:18`, `:174`). The flag comes only from the `label="Style"` line in `app.py`, so the names need Nimrod's eye on the PR.
- Deploy: none
