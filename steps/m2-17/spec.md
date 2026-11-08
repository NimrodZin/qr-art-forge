Class: top · Step: m2-17

# Spec — m2-17 · Stained glass out of the Style dropdown

## 1. Scope

**What changes (`styles.py` only)**
- Delete the `"Stained glass"` entry from `STYLES`, which is exactly the five lines `styles.py:21-25`. The diff to `styles.py` is 5 deletions and 0 additions.
- `STYLE_CHOICES` is derived from the table (`styles.py:37`), so it becomes `["None", "Mosaic", "Rug", "Embroidery"]` with no edit of its own.
- The dropdown reads `STYLE_CHOICES` (`app.py:13`, `app.py:266`), so `app.py` needs no edit.

**Why**
- Styles batch v2 measured Stained glass at 0/48 pass, also with rescue (`docs/04_Build_Plan.md:32`).
- Nimrod decided to remove it (`docs/04_Build_Plan.md:44`, `docs/05_Open_Discussion.md:18`).

**What does not change**
- The Mosaic, Rug and Embroidery entries: prompt suffix, negative suffix and strength 1.35, verbatim (`styles.py:16-20`, `styles.py:26-35`). Their order also stays: Mosaic, Rug, Embroidery.
- `STYLE_NONE`, `STYLE_NEGATIVE`, the `Style` tuple (`styles.py:5-12`), the module docstring (`styles.py:1-2`), `apply_style` (`styles.py:40-51`) and `style_strength` (`styles.py:54-58`).
- The None path. `apply_style` returns the same prompt and negative objects (`styles.py:43-44`), so default generation stays byte-identical.
- `app.py`, including `forge_with_style` and `strength_for_style` (`app.py:242-255`) and the Style dropdown's position and default (`app.py:266`).
- `validator.py`, `qrbuild.py`, `docs/`, `README.md` and `.github/`.
- The archive schema. The archive still records the effective prompt in its existing field (`tests/test_styles.py:396-406`).

**A removed value after this step**
- A request that still sends `"Stained glass"`, such as a browser tab opened before the change, is rejected by Gradio's Dropdown preprocess. It gets the same `gr.Error` as any out-of-choices value (`tests/test_styles.py:389-393`, `app.py:266`). No aliasing or remapping to another style is added.
- A direct call raises `KeyError` from `STYLES[name]` (`styles.py:45`, `styles.py:58`), as for any unknown name (`tests/test_styles.py:190-194`).

**Note for the Tester: edits to `tests/test_styles.py`**
- `CHOICES` (`tests/test_styles.py:33`) becomes `["None", "Mosaic", "Rug", "Embroidery"]`.
- Remove the `"Stained glass"` key from `SUFFIXES` (`tests/test_styles.py:38-39`). The tests parametrised on `list(SUFFIXES)` (`tests/test_styles.py:126`, `:137`, `:145`) then cover the three remaining styles without further edits.
- `test_table_holds_the_four_styles_verbatim` (`tests/test_styles.py:132-134`) names four styles and should be renamed for three.
- After the edits, `test_choices_in_order` (`tests/test_styles.py:121-123`), the renamed table test and `test_ui_has_one_style_dropdown` (`tests/test_styles.py:443-450`) fail on main, because main still has the entry. Rows 5 to 8 below add further tests.
- No other test file references a style name. `tests/test_styles.py` and `styles.py` are the only files outside `docs/` and `steps/` that contain `Embroidery` or `Stained`.

## 2. Behaviour table

"Handler" means `ui.dep.fn` (`tests/test_styles.py:69-74`), called directly. "Gradio path" means `process_api` (`tests/test_styles.py:363-364`). Generation is always mocked.

| # | Input | Observable result |
|---|---|---|
| 1 | `styles.STYLE_CHOICES` | Exactly `["None", "Mosaic", "Rug", "Embroidery"]`, in that order. |
| 2 | `styles.STYLES` | Keys are exactly `Mosaic`, `Rug`, `Embroidery`, in that order. |
| 3 | `prompt_suffix`, `negative_suffix`, `strength` of each remaining style | Each `prompt_suffix` equals its verbatim text in `SUFFIXES` (`tests/test_styles.py:36-44`, minus the removed key). `negative_suffix` is `"text, letters, words, watermark, signature"`. `strength` is `1.35`. |
| 4 | `app.build_ui()`, the `Style` dropdown | One dropdown. Default value `"None"`. Choice values are exactly those of row 1. `allow_custom_value` is `False`. It still sits between `Image prompt` and `Advanced` (`tests/test_styles.py:453-471`). |
| 5 | `apply_style("Stained glass", "a cat", "")` and `style_strength("Stained glass")` | Each raises `KeyError`. |
| 6 | Gradio path, Style `"Stained glass"` (`inputs_for`, `tests/test_styles.py:348-349`) | Raises `gr.Error` whose message contains `"Stained glass"`. `run_forge` is not reached. |
| 7 | Handler, Style `"Stained glass"`, `app.forge` recorded with the `forge_calls` fixture (`tests/test_styles.py:77-87`) | Raises `KeyError`, which is not converted to the "Couldn't forge" report (`app.py:244-245`). `forge` is never called. |
| 8 | Text of `styles.py` | Contains no `stained` in any letter case. Still has stdlib-only imports and no `validate` token (`tests/test_styles.py:206-216`). |
| 9 | Each remaining style through `apply_style("a cat", ...)` with user negative `"people"` | Prompt is `"a cat, " + suffix`. Negative is `"people, " + STYLE_NEGATIVE`. |
| 10 | `style_strength` for each remaining style; the Style change handler (`tests/test_styles.py:428-432`) | Returns `1.35`. The handler sets the slider to the table value. |
| 11 | `apply_style` with `"None"` and with `None` (`tests/test_styles.py:172-181`) | Returns the same prompt and negative objects. |
| 12 | Handler with Style `"None"` against a direct `run_forge` on the same inputs (`tests/test_styles.py:242-269`) | Same arguments reach `gen`, same negative, same report. Default generation stays byte-identical. |
| 13 | `/forge` API info (`tests/test_styles.py:474-477`) | The endpoint remains, with 12 parameters. |

Rows 11 to 13 are existing tests that must stay green unchanged.

## 3. Editable paths

`styles.py,tests/`

- Implementer: `styles.py` only, limited to deleting lines 21-25.
- Tester: `tests/test_styles.py` is the only test file that needs changes.

## 4. Class and lane

- Class: scoped.
- Lane: ordinary.
- This step touches no never-economize path: not `validator.py`, not `qrbuild.py`, not `README.md` front-matter, not `.github/`, not the THE GATE line in `app.py`.
- GPU: the queue line says `touches_gpu=no`, and the step edits none of `app.py`, `qrbuild.py` or `validator.py` (`docs/06_Loop_Spec.md:12`).
- UI: one user-visible dropdown choice disappears. Flag the PR body and label it `ui-change` (`docs/06_Loop_Spec.md:49`). The removal itself is Nimrod's decision (`docs/04_Build_Plan.md:44`).

## 5. Blocking questions

None

## Handover
- pytest -q: not run (read-only role)
- Files changed: None (the orchestrator writes steps/m2-17/spec.md)
- Not certain: (1) The behaviour table has not been run, because this role is read-only. (2) Outside this step's paths, the git-ignored `local/styles_batch_v2.py:58` still lists Stained glass and stops with exit code 2 at `local/styles_batch_v2.py:538-541` once it is gone. A rerun of that batch needs its own edit, and its `--run` viewer rebuild path returns earlier at `:536` and is unaffected. (3) The batch evidence for the removal is taken from `docs/04_Build_Plan.md:32`; the run directory was not read.
- Deploy: none
