"""m2-6: negative prompt field under Advanced (OD 9). Rows refer to steps/m2-6/spec.md §2."""
import pytest
from PIL import Image
import app
from qrbuild import make_qr

PAY = "nimrodzin.com"
GOOD = make_qr("https://" + PAY)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))
NEG_LITERAL = ("ugly, disfigured, low quality, blurry, nsfw, text, watermark, "
               "flat, grid, checkerboard, monochrome squares")
LABEL = "Negative prompt (added to the built-in list)"


@pytest.fixture(autouse=True)
def no_archive_env(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)


def recording_pipes(gen_imgs, rescue_img=BAD):
    calls = {"gen": [], "rescue": []}

    def gen(*a, **k):
        calls["gen"].append((a, k))
        return list(gen_imgs)

    def rescue(*a, **k):
        calls["rescue"].append((a, k))
        return rescue_img
    return {"gen": gen, "rescue": rescue}, calls


# ---------------------------------------------------------------- build_negative (rows 1-6)
@pytest.mark.parametrize("extra", ["", None, "   \n\t "])
def test_build_negative_empty_returns_default(extra):  # rows 1-3, 6
    assert app.build_negative(extra) == app.NEG == NEG_LITERAL


def test_build_negative_appends_user_text():  # row 4
    assert app.build_negative("people, hands") == app.NEG + ", people, hands"


def test_build_negative_strips_outer_whitespace_only():  # row 5
    assert app.build_negative("  red  ") == app.NEG + ", red"


# ---------------------------------------------------------------- run_forge wiring (rows 7-13)
def test_gen_gets_default_negative_when_omitted():  # row 7
    pipes, calls = recording_pipes([BAD])
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes)
    (_, k), = calls["gen"]
    assert k["negative"] == app.NEG


def test_gen_gets_user_negative_appended():  # row 8
    pipes, calls = recording_pipes([BAD])
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes, negative="people")
    (_, k), = calls["gen"]
    assert k["negative"] == app.NEG + ", people"


def test_gen_whitespace_negative_is_default():  # row 9
    pipes, calls = recording_pipes([BAD])
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes, negative="   ")
    (_, k), = calls["gen"]
    assert k["negative"] == app.NEG


def test_rescue_gets_same_negative_as_gen(monkeypatch):  # row 10
    real_validate = app.validate
    near = {"pass": False, "score": 1, "max": 3,
            "results": {c: {"zx": c == "full", "cv": False} for c in ("full", "small", "tilt")}}
    monkeypatch.setattr(app, "validate",
                        lambda im, p: near if im is BAD else real_validate(im, p))
    pipes, calls = recording_pipes([BAD], rescue_img=GOOD)
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, True, 1, pipes=pipes, negative="people")
    assert len(calls["rescue"]) == 1
    (_, gk), = calls["gen"]
    (_, rk), = calls["rescue"]
    assert rk["negative"] == app.NEG + ", people" == gk["negative"]


@pytest.mark.parametrize("kw", [{}, {"negative": "people"}])
def test_gen_positional_args_unchanged(kw):  # row 11
    pipes, calls = recording_pipes([BAD])
    app.run_forge(PAY, "a peony", 3, 1.35, 25, 7, False, 42, pipes=pipes, **kw)
    (a, k), = calls["gen"]
    assert a == ("a peony", a[1], 3, 1.35, 25, 7.0, 42)
    assert isinstance(a[6], int)
    assert a[1].size == make_qr("https://" + PAY).size
    assert set(k) == {"negative"}


def test_survivors_and_report_unchanged_with_negative():  # row 12
    pipes, _ = recording_pipes([GOOD, BAD, BAD])
    surv, report, _ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1,
                                    pipes=pipes, negative="people")
    assert len(surv) == 1 and surv[0][0] is GOOD
    assert "1/3 passed" in report
    assert report.splitlines()[-1] == "rejects not archived (HF_TOKEN/REJECTS_REPO unset)"


def test_reject_archive_settings_have_no_negative_key(monkeypatch):  # row 13
    seen = {}
    monkeypatch.setattr(app, "archive_rejects",
                        lambda r: (seen.setdefault("r", r), "x")[1])
    pipes, _ = recording_pipes([GOOD, BAD, BAD])
    app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1, pipes=pipes, negative="people")
    assert len(seen["r"]) == 2
    for _, _, meta in seen["r"]:
        assert set(meta["settings"]) == {"prompt", "batch", "weight", "steps", "cfg",
                                         "rescue", "seed"}


# ---------------------------------------------------------------- forge (rows 14-15)
def _capture_run_forge(monkeypatch):
    seen = {}

    def fake(*a, **k):
        seen["a"], seen["k"] = a, k
        return [], "", None
    monkeypatch.setattr(app, "run_forge", fake)
    return seen


def test_forge_forwards_negative(monkeypatch):  # row 14
    seen = _capture_run_forge(monkeypatch)
    app.forge(PAY, "p", 1, 1.35, 25, 7, False, 1, "people")
    assert seen["k"].get("negative") == "people"


def test_forge_negative_defaults_to_empty(monkeypatch):  # row 15
    seen = _capture_run_forge(monkeypatch)
    app.forge(PAY, "p", 1, 1.35, 25, 7, False, 1)
    assert "negative" in seen["k"]
    assert seen["k"]["negative"] == ""


# ---------------------------------------------------------------- UI (rows 16-19)
def _neg_boxes(demo):
    import gradio as gr
    return [b for b in demo.blocks.values()
            if isinstance(b, gr.Textbox) and b.label == LABEL]


def test_ui_has_one_negative_textbox():  # row 16
    boxes = _neg_boxes(app.build_ui())
    assert len(boxes) == 1
    assert boxes[0].value == ""
    assert boxes[0].lines == 2


def test_negative_textbox_is_inside_advanced():  # row 17
    import gradio as gr
    (box,) = _neg_boxes(app.build_ui())
    node, ancestors = box.parent, []
    while node is not None:
        ancestors.append(node)
        node = node.parent
    assert any(isinstance(n, gr.Accordion) and n.label == "Advanced" for n in ancestors)


def test_forge_click_inputs_end_with_negative():  # row 18, 19
    import gradio as gr
    demo = app.build_ui()
    (box,) = _neg_boxes(demo)
    (btn,) = [b for b in demo.blocks.values() if isinstance(b, gr.Button) and b.value == "Forge"]
    (dep,) = [f for f in demo.fns.values() if (btn._id, "click") in f.targets]
    ins = dep.inputs
    assert len(ins) == 9
    assert ins[8] is box
    expected = [(gr.Textbox, "URL or text"), (gr.Textbox, "Image prompt"),
                (gr.Slider, "Batch size"),
                (gr.Slider, "QR strength (higher = scans easier, looks more like a code)"),
                (gr.Slider, "Steps"), (gr.Slider, "Guidance (CFG)"),
                (gr.Checkbox, "Rescue near-misses"), (gr.Number, "Seed (-1 = random)")]
    assert [(type(c), c.label) for c in ins[:8]] == expected
    demo.get_api_info()  # row 19
