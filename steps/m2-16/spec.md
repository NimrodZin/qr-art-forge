Class: top · Step: m2-16

# Spec — m2-16 · Visible errors

## 1. Scope

**What changes (app.py only, inside `build_ui()`)**
- Only the body of `forge_with_style` changes (`app.py:242-246`). The `forge(...)` call (`app.py:245-246`) goes inside `try: … except gr.Error as e:`. When that error is caught, the handler:
  1. builds `text = "Couldn't forge: " + e.message`. The apostrophe is the ASCII U+0027, matching `REF_ERROR` at `app.py:23`.
  2. calls `gr.Warning(text)` exactly once.
  3. returns `([], text, None)`, in output order: gallery, Scan report, control image (`app.py:283-285`).
- Use `e.message`, not `str(e)`. `gr.Error.__str__` returns `repr(self.message)` (`.venv/Lib/site-packages/gradio/exceptions.py:97-98`), so `str(e)` would add quotes.
- The call `apply_style(style_name, prompt, negative)` (`app.py:244`) stays outside the `try`.
- The success path returns forge's return value as the same object. Nothing is wrapped or copied, so default generation stays byte-identical.

**Where the errors come from today**
- `forge` turns `PayloadError` into `gr.Error(str(e))` (`app.py:226-227`).
- `normalize_payload` raises two messages:
  - `"Enter a URL or text to encode."` for empty or whitespace input (`qrbuild.py:21-23`).
  - `"Payload is {n} characters; limit is 80. Use a short link."` for anything over 80 characters (`qrbuild.py:28-30`).

**What does not change**
- `forge` (`app.py:219-227`) and `run_forge` (`app.py:170-216`).
- THE GATE line (`app.py:205`) and the validator import (`app.py:15`).
- `reference_preprocess` (`app.py:231-238`), `strength_for_style` (`app.py:248-250`), the layout and wiring (`app.py:252-289`), `qrbuild.py` and `styles.py`.
- No added line contains the token `validate`.
- No new UI component, no new input or output, no change to `api_name="forge"`.
- Exceptions that are not `gr.Error` still propagate unchanged. They are not caught, logged or converted.
- Errors raised before the handler runs keep today's error modal:
  - Gradio preprocess errors for the reference image (`REF_ERROR`, from m2-9b).
  - Gradio preprocess errors for an out-of-choices Style value.
- The reject archive is not touched. On the error path `run_forge` raises at `app.py:176`, before `archive_rejects` at `app.py:214`, as it does today.

**Out of scope (observed, not changed)**
- `run_forge` calls `get_pipes()` (`app.py:175`) before `normalize_payload` (`app.py:176`), and `forge` runs under `@GPU` (`app.py:219`). So an empty-URL click still loads the pipelines and, on the Space, takes a GPU slot. Moving the payload check earlier would mean editing `run_forge`/`forge`, which this step must not do.

**Note for the Tester**
- Error-path tests that go through the real `forge`/`run_forge` must stub `app.get_pipes`, because of `app.py:175`.
- `pipes["gen"]` must not be called on those paths; it is only reached at `app.py:184`.
- One existing test must be rewritten: `tests/test_styles.py:335-343` (`test_long_payload_is_still_rejected`, row 22) expects the handler to raise `gr.Error`. Row 2 below replaces it.

## 2. Behaviour table

"Handler" means `ui.dep.fn`, the Forge click dependency's function (`tests/test_styles.py:69-74`), called directly. "Gradio path" means `demo.process_api(dep, inputs, state=SessionState(demo))` (`tests/test_styles.py:365-366`). Generation is always mocked.

| # | Input | Observable result |
|---|---|---|
| 1 | Handler, style `None` and also `Mosaic`, payload `""` and also `"   "`. Real `forge`/`run_forge`, `app.get_pipes` stubbed. | No exception. Returns a 3-tuple: `[]` (an empty list), `"Couldn't forge: Enter a URL or text to encode."`, and `None`. `gen` and `rescue` are never called. |
| 2 | Handler, payload `"https://example.com/" + "x"*80`. Real forge path, pipes stubbed. Replaces `test_styles.py:335-343`. | No exception. Returns `([], "Couldn't forge: " + str(PayloadError), None)`, where `PayloadError` is what `normalize_payload` raises for that payload. `gen` is never called. |
| 3 | Handler, `app.forge` monkeypatched to raise `gr.Error("boom")`. | Returns `([], "Couldn't forge: boom", None)`. The report string has no quote characters around `boom`, which shows `e.message` was used, not `repr`. |
| 4 | Rows 1–3, with `gr.Warning` observed (monkeypatch `gradio.Warning`, or `pytest.warns(UserWarning)` because a direct call has no event context, `helpers.py:1133-1141`). | `gr.Warning` is called exactly once per call. Its message equals the returned report string exactly. |
| 5 | Handler, `app.forge` monkeypatched to raise `RuntimeError("x")` and also `ValueError("y")`. | The same exception object propagates, with type unchanged. Nothing is returned and `gr.Warning` is not called. |
| 6 | Handler, `app.forge` monkeypatched to return a sentinel (existing `test_styles.py:346-347`). | The return value `is` the sentinel. `gr.Warning` is not called. |
| 7 | Handler, real forge path, `PAY` (a normal short URL), `GOOD`/`BAD` images (as in `test_styles.py:326-332`). | Same as today: survivors pass the gate and the report starts `"1/3 passed"`. The report does not contain `"Couldn't forge"`. `gr.Warning` is not called. |
| 8 | Handler, real path, a 41–80 character payload (warn band, `qrbuild.py:32-33`). | This is a success, not an error. The report contains the long-payload warning as today. No `"Couldn't forge"`, and `gr.Warning` is not called. |
| 9 | Gradio path, payload `""`, real `forge`/`run_forge`, `app.get_pipes` stubbed. | `process_api` does not raise. Output data: the gallery is empty, the Scan report is `"Couldn't forge: Enter a URL or text to encode."`, and the control image is `None`. `gen` is never called. |
| 10 | Gradio path, the 101-character payload from row 2. | Same as row 9, with the report `"Couldn't forge: " + str(PayloadError)`. |
| 11 | Gradio path, AVIF or purged reference upload (existing `test_reference_errors.py:197-208`). | Unchanged: `process_api` raises `gr.Error` with `REF_ERROR`, and `run_forge` is not reached. |
| 12 | Gradio path, Style `"Nope"` (existing `test_styles.py:391-395`). | Unchanged: raises `gr.Error` whose message contains `"Nope"`, and `run_forge` is not reached. |
| 13 | `app.forge` called directly with payload `""`, pipes stubbed. | Still raises `gr.Error` with message `"Enter a URL or text to encode."`. This shows `forge` itself is unchanged. |
| 14 | Click wiring (existing `test_styles.py:220-239`, `test_negative.py:164-182`). | Unchanged: 12 inputs; outputs are Gallery "Scannable results", Textbox "Scan report", Image "Control image used". The handler still has 13 parameters, with the last named `progress` and defaulting to `gr.Progress`. `tracks_progress` is True and `demo.get_api_info()` runs. |
| 15 | Style `None` and a direct handler call (existing `test_styles.py:242-270`). | Unchanged: the same eleven objects go to `forge`, plus `progress`. Generation matches a direct `run_forge` call. |
| 16 | `app.py` source. | Exactly one line contains `THE GATE`, and it is unchanged: `if v["pass"]:  # THE GATE — the only way into the gallery`. The string `Couldn't forge` appears only inside `build_ui`, not in `forge` or `run_forge` (check with `inspect.getsource`). |

## 3. Editable paths

- `app.py`: Implementer. Only the body of `forge_with_style`.
- `tests/`: Tester only. This includes rewriting `tests/test_styles.py:335-343` and the new rows.

The Implementer may not touch `tests/`, `docs/` or `steps/`.

## 4. Class and lane

- **Class: scoped.** **Lane: ordinary.**
- No never-economize path is touched: not `validator.py`, `qrbuild.py`, `README.md`, `.github/`, nor THE GATE line or the `run_forge`/`forge` gate spans in `app.py`. A diff that touches any of them, the validator import, or adds a `validate` token must stop (06 §3).
- **ui-change:** this adds a user-visible string, `Couldn't forge: <message>`, in the Scan report and in the toast. The wording is a default, flagged in the PR body (06 §4).
- The step touches `app.py`, so the orchestrator runs the real-generation check (06 §1a). This spec defines no GPU test.

## 5. Blocking questions

None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-16/spec.md)
- Not certain:
  1. How ZeroGPU passes errors through is unverified: the `spaces` package is not installed locally. `spaces.GPU` may re-raise a worker's `gr.Error` unchanged, and it may also turn non-Gradio worker exceptions or quota errors into `gr.Error`. If it does, on the Space those would also show as `Couldn't forge: …` rather than a modal. CPU and CI behaviour is not affected.
  2. `gr.Warning` renders its message as HTML (`helpers.py:1164`). Today's messages contain no user text. A future `gr.Error` that echoes user input would be rendered as HTML in the toast.
  3. The toast has not been seen in a browser. It depends on the queue, which is enabled at `app.py:293`; screenshots are deferred (OD 11).
- Deploy: none
