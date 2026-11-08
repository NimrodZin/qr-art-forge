"""m2-15: style presets on the main path (OD 14, order B). Rows refer to steps/m2-15/spec.md §2,
except the m2-17 section at the end, whose rows refer to steps/m2-17/spec.md §2.
CPU only; generation is mocked. `styles` is imported inside each test so that a missing module
fails the tests one by one."""
import ast
import asyncio
import importlib
import inspect
import re
import sys
import tomllib
import types
from pathlib import Path

import gradio as gr
import pytest
from gradio.layouts import Form
from gradio.state_holder import SessionState
from PIL import Image

import app
import validator
from qrbuild import PayloadError, make_qr, normalize_payload

ROOT = Path(__file__).resolve().parent.parent
PAY = "nimrodzin.com"
PROMPT = "a peony in full bloom"
GOOD = make_qr("https://" + PAY)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))
SETTINGS_KEYS = {"prompt", "batch", "weight", "steps", "cfg", "rescue", "seed"}
META_KEYS = {"run_id", "label", "payload", "settings", "pass", "score", "max", "results",
             "reference"}
STRENGTH_LABEL = "QR strength (higher = scans easier, looks more like a code)"
CHOICES = ["None", "Mosaic", "Rug", "Embroidery"]
STYLE_NEG = "text, letters, words, watermark, signature"
SUFFIXES = {
    "Mosaic": ("as an ancient Roman floor mosaic, small square marble and lapis tesserae, "
               "irregular grout, soft daylight, photographed from directly above"),
    "Rug": ("woven into a hand-knotted wool rug, dense pile, natural dyes, geometric border, "
            "photographed from directly above"),
    "Embroidery": ("as hand embroidery on natural linen, french knots and satin stitch, "
                   "colourful silk threads, macro photograph, front view"),
}
MOSAIC_PROMPT = PROMPT + ", " + SUFFIXES["Mosaic"]


def S():
    """The module under test, imported per test: see the module docstring."""
    return importlib.import_module("styles")


@pytest.fixture(autouse=True)
def no_archive_env(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)


@pytest.fixture(autouse=True)
def gradio_cache(monkeypatch, tmp_path):
    """Blocks read the cache dir when built; keep test copies out of the real Gradio cache."""
    monkeypatch.setenv("GRADIO_TEMP_DIR", str(tmp_path / "gradio_cache"))


def components(demo, kind, label):
    return [b for b in demo.blocks.values() if isinstance(b, kind) and b.label == label]


@pytest.fixture
def ui():
    demo = app.build_ui()
    (btn,) = [b for b in demo.blocks.values() if isinstance(b, gr.Button) and b.value == "Forge"]
    (dep,) = [f for f in demo.fns.values() if (btn._id, "click") in f.targets]
    return types.SimpleNamespace(demo=demo, dep=dep)


@pytest.fixture
def forge_calls(monkeypatch):
    """Record what the handler hands to app.forge, which returns the sentinel `result`."""
    calls = []
    result = object()

    def fake(*a, **k):
        calls.append((a, k))
        return result
    monkeypatch.setattr(app, "forge", fake)
    return types.SimpleNamespace(calls=calls, result=result)


def recording_pipes(gen_imgs, rescue_img=BAD):
    calls = {"gen": [], "rescue": []}

    def gen(*a, **k):
        calls["gen"].append((a, k))
        return list(gen_imgs)

    def rescue(*a, **k):
        calls["rescue"].append((a, k))
        return rescue_img
    return {"gen": gen, "rescue": rescue}, calls


def use_pipes(monkeypatch, gen_imgs, rescue_img=BAD):
    pipes, calls = recording_pipes(gen_imgs, rescue_img)
    monkeypatch.setattr(app, "get_pipes", lambda: pipes)
    return calls


def no_progress(*a, **k):
    pass


def call_handler(ui, style="Mosaic", *, payload=PAY, prompt=PROMPT, batch=1, weight=1.35, steps=25,
                 cfg=7, rescue=False, seed=1, negative="", reference=None, reference_scale=0.5,
                 progress=no_progress):
    return ui.dep.fn(payload, prompt, batch, weight, steps, cfg, rescue, seed, negative,
                     reference, reference_scale, style, progress=progress)


# ---------------------------------------------------------------- styles.py (rows 1-11)
def test_choices_in_order():  # row 1
    assert S().STYLE_CHOICES == CHOICES
    assert S().STYLE_NONE == "None"


@pytest.mark.parametrize("name", list(SUFFIXES))
def test_prompt_gets_the_exact_suffix(name):  # row 2
    prompt, _ = S().apply_style(name, "a cat", "")
    assert prompt == "a cat, " + SUFFIXES[name]


def test_table_holds_the_three_styles_verbatim_in_order():  # row 2, 3; m2-17 rows 2, 3
    assert list(S().STYLES) == ["Mosaic", "Rug", "Embroidery"]
    assert {n: st.prompt_suffix for n, st in S().STYLES.items()} == SUFFIXES


@pytest.mark.parametrize("name", list(SUFFIXES))
def test_table_negative_and_strength(name):  # row 3
    entry = S().STYLES[name]
    assert entry.negative_suffix == STYLE_NEG == S().STYLE_NEGATIVE
    assert entry.strength == 1.35
    assert 0.8 <= entry.strength <= 2.0


@pytest.mark.parametrize("name", list(SUFFIXES))
def test_every_style_appends_its_negative(name):  # row 4 across the table
    _, negative = S().apply_style(name, "a cat", "people")
    assert negative == "people, " + STYLE_NEG


def test_user_negative_comes_first():  # row 4
    _, negative = S().apply_style("Mosaic", "a cat", "people")
    assert negative == "people, text, letters, words, watermark, signature"


@pytest.mark.parametrize("empty", ["", None, "  \n\t "])
def test_empty_user_negative_leaves_style_negative_alone(empty):  # row 5
    _, negative = S().apply_style("Mosaic", "a cat", empty)
    assert negative == "text, letters, words, watermark, signature"


def test_user_negative_is_stripped():  # row 6
    _, negative = S().apply_style("Mosaic", "a cat", "  red  ")
    assert negative == "red, text, letters, words, watermark, signature"


def test_user_prompt_is_not_trimmed():  # §1 semantics, "exactly as written, with no trimming"
    prompt, _ = S().apply_style("Mosaic", "  a cat \n", "")
    assert prompt == "  a cat \n, " + SUFFIXES["Mosaic"]


@pytest.mark.parametrize("style", ["None", None])
@pytest.mark.parametrize("neg", ["", None, "  red  "])
@pytest.mark.parametrize("prompt", ["a cat", ""])
def test_none_style_returns_the_same_objects(style, neg, prompt):  # row 7
    # non-interned copies, so `is` proves pass-through rather than equal literals
    p = "".join(list(prompt))
    n = None if neg is None else "".join(list(neg))
    out_p, out_n = S().apply_style(style, p, n)
    assert out_p is p
    assert out_n is n


def test_empty_prompt_keeps_the_literal_formula():  # row 8
    prompt, negative = S().apply_style("Mosaic", "", "")
    assert prompt == ", " + SUFFIXES["Mosaic"]
    assert negative == STYLE_NEG


def test_unknown_name_is_a_key_error():  # row 9
    with pytest.raises(KeyError):
        S().apply_style("Nope", "p", "")
    with pytest.raises(KeyError):
        S().style_strength("Nope")


def test_style_strength_reads_the_table_at_call_time(monkeypatch):  # row 10
    styles = S()
    assert styles.style_strength("Mosaic") == 1.35
    assert styles.style_strength("None") is None
    assert styles.style_strength(None) is None
    monkeypatch.setitem(styles.STYLES, "Mosaic", styles.STYLES["Mosaic"]._replace(strength=1.6))
    assert styles.style_strength("Mosaic") == 1.6


def test_module_imports_stdlib_only_and_has_no_validate_token():  # row 11
    source = Path(S().__file__).read_text(encoding="utf-8")
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            roots.add(node.module.split(".")[0])
    assert roots <= set(sys.stdlib_module_names)
    assert not re.search(r"\bvalidate\b", source)


# ---------------------------------------------------------------- forge_with_style (rows 12-26)
def test_forge_click_inputs_and_outputs(ui):  # row 12
    expected = [(gr.Textbox, "URL or text"), (gr.Textbox, "Image prompt"),
                (gr.Slider, "Batch size"), (gr.Slider, STRENGTH_LABEL),
                (gr.Slider, "Steps"), (gr.Slider, "Guidance (CFG)"),
                (gr.Checkbox, "Rescue near-misses"), (gr.Number, "Seed (-1 = random)"),
                (gr.Textbox, "Negative prompt (added to the built-in list)"),
                (gr.Image, "Style reference image (optional)"),
                (gr.Slider, "Reference strength"), (gr.Dropdown, "Style")]
    assert [(type(c), c.label) for c in ui.dep.inputs] == expected
    assert [(type(c), c.label) for c in ui.dep.outputs] == [
        (gr.Gallery, "Scannable results"), (gr.Textbox, "Scan report"),
        (gr.Image, "Control image used")]


def test_handler_tracks_progress(ui):  # row 13
    assert ui.dep.tracks_progress is True
    params = list(inspect.signature(ui.dep.fn).parameters.values())
    assert len(params) == 13
    assert params[-1].name == "progress"
    assert isinstance(params[-1].default, gr.Progress)


def test_none_style_hands_forge_the_same_eleven_values(ui, forge_calls):  # row 14
    sentinel = object()
    values = [object() for _ in range(11)]
    ui.dep.fn(*values, "None", progress=sentinel)
    ((a, k),) = forge_calls.calls
    assert len(a) == 11
    assert all(got is want for got, want in zip(a, values))
    assert set(k) == {"progress"}
    assert k["progress"] is sentinel


def test_none_style_generation_matches_a_direct_run(ui, monkeypatch):  # row 15
    ticks = []
    calls = use_pipes(monkeypatch, [BAD, BAD, BAD, BAD])
    styled = ui.dep.fn(PAY, PROMPT, 4, 1.35, 25, 7, True, 12345, "", None, 0.5, "None",
                       progress=lambda *a, **k: ticks.append((a, k)))
    direct_pipes, direct_calls = recording_pipes([BAD, BAD, BAD, BAD])
    direct = app.run_forge(PAY, PROMPT, 4, 1.35, 25, 7, True, 12345, pipes=direct_pipes)

    ((a, k),) = calls["gen"]
    ((da, dk),) = direct_calls["gen"]
    assert a[0] == da[0] == PROMPT
    assert a[1].tobytes() == da[1].tobytes()
    assert a[2:] == da[2:] == (4, 1.35, 25, 7.0, 12345)
    assert [type(x) for x in a] == [type(x) for x in da]
    assert set(k) == set(dk) == {"negative"}
    assert k["negative"] == dk["negative"] == app.NEG
    assert styled[1] == direct[1]
    assert ticks  # the handler's progress reached run_forge


def test_named_style_hands_forge_the_effective_text(ui, forge_calls):  # row 16
    sentinel = object()
    ref = object()
    ui.dep.fn(PAY, PROMPT, 3, 1.5, 20, 8, True, 7, "people", ref, 0.7, "Mosaic", progress=sentinel)
    ((a, k),) = forge_calls.calls
    assert a[1] == MOSAIC_PROMPT
    assert a[8] == "people, " + STYLE_NEG
    assert a[0] == PAY
    assert a[2:8] == (3, 1.5, 20, 8, True, 7)
    assert a[9] is ref
    assert a[10] == 0.7
    assert k["progress"] is sentinel


def test_style_never_overrides_the_slider(ui, forge_calls, monkeypatch):  # row 17
    call_handler(ui, weight=1.6)
    styles = S()
    monkeypatch.setitem(styles.STYLES, "Mosaic", styles.STYLES["Mosaic"]._replace(strength=1.9))
    call_handler(ui, weight=1.6)
    assert [a[3] for a, _ in forge_calls.calls] == [1.6, 1.6]


def test_gen_gets_effective_prompt_and_negative(ui, monkeypatch):  # row 18
    calls = use_pipes(monkeypatch, [BAD])
    call_handler(ui)
    ((a, k),) = calls["gen"]
    assert a[0] == MOSAIC_PROMPT
    assert k["negative"] == app.NEG + ", text, letters, words, watermark, signature"


def test_rescue_gets_the_same_effective_text_as_gen(ui, monkeypatch):  # row 19
    real_validate = app.validate
    near = {"pass": False, "score": 1, "max": 3,
            "results": {c: {"zx": c == "full", "cv": False} for c in ("full", "small", "tilt")}}
    monkeypatch.setattr(app, "validate",
                        lambda im, p: near if im is BAD else real_validate(im, p))
    calls = use_pipes(monkeypatch, [BAD], rescue_img=GOOD)
    call_handler(ui, rescue=True, negative="people")
    ((ga, gk),) = calls["gen"]
    ((ra, rk),) = calls["rescue"]
    assert ra[0] == ga[0] == MOSAIC_PROMPT
    assert rk["negative"] == gk["negative"] == app.NEG + ", people, " + STYLE_NEG


def test_style_keeps_the_reference(ui, monkeypatch):  # row 20
    calls = use_pipes(monkeypatch, [BAD])
    ref = Image.new("RGB", (37, 23), (200, 10, 120))
    call_handler(ui, reference=ref, reference_scale=0.7)
    ((_, k),) = calls["gen"]
    assert k["reference"] is ref
    assert k["reference_scale"] == 0.7


def test_gate_still_decides_with_a_style(ui, monkeypatch):  # row 21
    use_pipes(monkeypatch, [GOOD, BAD, BAD])
    surv, report, _ = call_handler(ui, batch=3)
    assert len(surv) == 1
    assert surv[0][0] is GOOD
    assert all(im is not BAD for im, _ in surv)
    assert "1/3 passed" in report


def test_long_payload_is_still_rejected(ui, monkeypatch):  # m2-16 row 2, replacing m2-15 row 22
    long_payload = "https://example.com/" + "x" * 80
    with pytest.raises(PayloadError) as want:
        normalize_payload(long_payload)
    calls = use_pipes(monkeypatch, [GOOD])
    assert call_handler(ui, payload=long_payload) == ([], "Couldn't forge: " + str(want.value), None)
    assert calls["gen"] == []


def test_handler_returns_what_forge_returns(ui, forge_calls):  # row 23
    assert call_handler(ui) is forge_calls.result


def inputs_for(style, negative=""):
    return [PAY, PROMPT, 1, 1.35, 25, 7, False, 1, negative, None, 0.5, style]


@pytest.fixture
def run_forge_calls(monkeypatch):
    calls = []

    def record(*a, **k):
        calls.append((a, k))
        return [], "report", None
    monkeypatch.setattr(app, "run_forge", record)
    return calls


def process_api(ui, inputs):
    return asyncio.run(ui.demo.process_api(ui.dep, inputs, state=SessionState(ui.demo)))


def test_gradio_path_reaches_run_forge_with_effective_text(ui, run_forge_calls):  # row 24
    process_api(ui, inputs_for("Mosaic", "people"))
    ((a, k),) = run_forge_calls
    assert a[0] == PAY
    assert a[1] == MOSAIC_PROMPT
    assert k["negative"] == "people, " + STYLE_NEG


def test_gradio_path_none_style_reaches_run_forge_untouched(ui, run_forge_calls):  # row 24 guard
    process_api(ui, inputs_for("None"))
    ((a, k),) = run_forge_calls
    assert a[1] == PROMPT
    assert k["negative"] == ""


def test_gradio_path_null_style_reaches_run_forge_untouched(ui, run_forge_calls):  # §1, null payload
    process_api(ui, inputs_for(None))
    ((a, k),) = run_forge_calls
    assert a[1] == PROMPT
    assert k["negative"] == ""


def test_gradio_path_rejects_an_unknown_style(ui, run_forge_calls):  # row 25
    with pytest.raises(gr.Error) as e:
        process_api(ui, inputs_for("Nope"))
    assert "Nope" in e.value.message
    assert run_forge_calls == []


def test_archive_sees_the_effective_prompt_and_no_new_keys(ui, monkeypatch):  # row 26
    seen = {}
    monkeypatch.setattr(app, "archive_rejects",
                        lambda r: (seen.setdefault("r", r), "x")[1])
    use_pipes(monkeypatch, [GOOD, BAD, BAD])
    call_handler(ui, batch=3, negative="people")
    assert len(seen["r"]) == 2
    for _, _, meta in seen["r"]:
        assert set(meta) == META_KEYS
        assert set(meta["settings"]) == SETTINGS_KEYS
        assert meta["settings"]["prompt"] == MOSAIC_PROMPT


# ---------------------------------------------------------------- slider (rows 27-29)
@pytest.fixture
def style_dep():
    demo = app.build_ui()
    (style,) = components(demo, gr.Dropdown, "Style")
    deps = [f for f in demo.fns.values() if (style._id, "change") in f.targets]
    assert len(deps) == 1
    return types.SimpleNamespace(demo=demo, style=style, dep=deps[0])


def test_style_change_targets_the_strength_slider(style_dep):  # row 27
    (slider,) = components(style_dep.demo, gr.Slider, STRENGTH_LABEL)
    assert len(style_dep.dep.inputs) == 1
    assert style_dep.dep.inputs[0] is style_dep.style
    assert len(style_dep.dep.outputs) == 1
    assert style_dep.dep.outputs[0] is slider
    assert style_dep.dep.queue is False


def test_style_change_sets_the_table_strength(style_dep, monkeypatch):  # row 28
    assert style_dep.dep.fn("Mosaic") == 1.35
    styles = S()
    monkeypatch.setitem(styles.STYLES, "Mosaic", styles.STYLES["Mosaic"]._replace(strength=1.6))
    assert style_dep.dep.fn("Mosaic") == 1.6


@pytest.mark.parametrize("name", ["None", None])
def test_none_style_leaves_the_slider_alone(style_dep, name):  # row 29
    assert style_dep.dep.fn(name) == gr.skip() == {"__type__": "update"}
    (slider,) = components(style_dep.demo, gr.Slider, STRENGTH_LABEL)
    assert slider.value == 1.35


# ---------------------------------------------------------------- UI and gate shape (rows 30-34)
def test_ui_has_one_style_dropdown():  # row 30
    drops = components(app.build_ui(), gr.Dropdown, "Style")
    assert len(drops) == 1
    (drop,) = drops
    assert drop.value == "None"
    assert [value for _, value in drop.choices] == CHOICES
    assert not drop.multiselect
    assert drop.allow_custom_value is False


def test_dropdown_sits_between_prompt_and_advanced():  # row 31
    demo = app.build_ui()
    (drop,) = components(demo, gr.Dropdown, "Style")
    (prompt,) = components(demo, gr.Textbox, "Image prompt")
    (advanced,) = components(demo, gr.Accordion, "Advanced")
    assert drop.parent is prompt.parent
    # Gradio groups consecutive form inputs in a Form inside the Column, on Blocks exit
    column = drop.parent.parent if isinstance(drop.parent, Form) else drop.parent
    assert advanced.parent is column
    order = []
    for child in column.children:
        order.extend(child.children if isinstance(child, Form) else [child])
    at = [c._id for c in order].index(drop._id)
    assert order[at - 1] is prompt
    assert order[at + 1] is advanced
    node = drop.parent
    while node is not None:
        assert not (isinstance(node, gr.Accordion) and node.label == "Advanced")
        node = node.parent


def test_api_info_keeps_the_forge_endpoint():  # row 32
    info = app.build_ui().get_api_info()
    assert "/forge" in info["named_endpoints"]
    assert len(info["named_endpoints"]["/forge"]["parameters"]) == 12


def test_gate_functions_and_import_are_untouched():  # row 33
    names = lambda fn: list(inspect.signature(fn).parameters)
    forge = inspect.signature(app.forge).parameters
    assert names(app.forge) == ["payload", "prompt", "batch", "weight", "steps", "cfg", "rescue",
                                "seed", "negative", "reference", "reference_scale", "progress"]
    assert forge["negative"].default == ""
    assert forge["reference"].default is None
    assert forge["reference_scale"].default == app.REF_SCALE
    assert isinstance(forge["progress"].default, gr.Progress)
    run = inspect.signature(app.run_forge).parameters
    assert names(app.run_forge) == ["payload_raw", "prompt", "batch", "weight", "steps", "cfg",
                                    "rescue", "seed", "pipes", "progress", "negative",
                                    "reference", "reference_scale"]
    assert run["pipes"].default is None
    assert run["progress"].default is None
    assert run["negative"].default == ""
    assert run["reference"].default is None
    assert run["reference_scale"].default == app.REF_SCALE
    assert app.validate is validator.validate


def test_gate_spans_on_the_working_tree():  # row 34
    gates = importlib.import_module("loop.gates")
    with open(ROOT / "loop" / "config.toml", "rb") as f:
        functions = tomllib.load(f)["never_economize"]["gate_functions"]
    assert functions == ["run_forge", "forge"]
    source = Path(app.__file__).read_text(encoding="utf-8")
    spans = gates.gate_spans(source, functions)
    assert len([s for s in spans if s[1] > s[0]]) == 2
    single = [s for s in spans if s[0] == s[1]]
    assert len(single) == 1
    assert source.splitlines()[single[0][0] - 1].startswith("from validator import")


# ---------------------------------------------------------------- m2-17: Stained glass out
REMOVED = "Stained glass"


def test_removed_style_is_an_unknown_name():  # m2-17 row 5
    with pytest.raises(KeyError):
        S().apply_style(REMOVED, "a cat", "")
    with pytest.raises(KeyError):
        S().style_strength(REMOVED)


def test_gradio_path_rejects_the_removed_style(ui, run_forge_calls):  # m2-17 row 6
    with pytest.raises(gr.Error) as e:
        process_api(ui, inputs_for(REMOVED))
    assert REMOVED in e.value.message
    assert run_forge_calls == []


def test_handler_raises_on_the_removed_style_without_forging(ui, forge_calls):  # m2-17 row 7
    with pytest.raises(KeyError):
        call_handler(ui, style=REMOVED)
    assert forge_calls.calls == []


def test_styles_module_no_longer_names_it():  # m2-17 row 8
    assert "stained" not in Path(S().__file__).read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("name", list(SUFFIXES))
def test_remaining_styles_keep_strength_and_slider(style_dep, name):  # m2-17 row 10
    styles = S()
    assert styles.style_strength(name) == 1.35
    assert style_dep.dep.fn(name) == styles.STYLES[name].strength == 1.35
