"""m2-16: a gr.Error from forge() shows in the Scan report and a toast. Rows refer to
steps/m2-16/spec.md §2. CPU only; generation is mocked.

Row 2 is test_styles.py::test_long_payload_is_still_rejected, rewritten. Rows 11, 12, 14 and 15 are
the existing tests the spec names: test_reference_errors.py::test_avif_never_reaches_generation and
::test_purged_never_reaches_generation; test_styles.py::test_gradio_path_rejects_an_unknown_style;
test_styles.py::test_forge_click_inputs_and_outputs, ::test_handler_tracks_progress,
::test_api_info_keeps_the_forge_endpoint and test_negative.py::test_forge_click_inputs_end_with_negative;
test_styles.py::test_none_style_hands_forge_the_same_eleven_values and
::test_none_style_generation_matches_a_direct_run."""
import asyncio
import inspect
import re
import types
from pathlib import Path

import gradio as gr
import pytest
from gradio.state_holder import SessionState
from PIL import Image

import app
from qrbuild import PayloadError, make_qr, normalize_payload

PAY = "nimrodzin.com"
PROMPT = "a peony in full bloom"
GOOD = make_qr("https://" + PAY)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))
EMPTY_MESSAGE = "Enter a URL or text to encode."
LONG_PAYLOAD = "https://example.com/" + "x" * 80  # 100 characters: over the limit
WARN_BAND_PAYLOAD = "https://example.com/" + "x" * 30  # 50 characters: warned, not rejected
GATE_LINE = 'if v["pass"]:  # THE GATE — the only way into the gallery'


def report_for(message):
    return "Couldn't forge: " + message


def long_payload_report():
    with pytest.raises(PayloadError) as want:
        normalize_payload(LONG_PAYLOAD)
    return report_for(str(want.value))


def raiser(exc):
    def fake(*a, **k):
        raise exc
    return fake


def no_progress(*a, **k):
    pass


@pytest.fixture(autouse=True)
def no_archive_env(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)


@pytest.fixture(autouse=True)
def gradio_cache(monkeypatch, tmp_path):
    """Blocks read the cache dir when built; keep test copies out of the real Gradio cache."""
    monkeypatch.setenv("GRADIO_TEMP_DIR", str(tmp_path / "gradio_cache"))


@pytest.fixture
def ui():
    demo = app.build_ui()
    (btn,) = [b for b in demo.blocks.values() if isinstance(b, gr.Button) and b.value == "Forge"]
    (dep,) = [f for f in demo.fns.values() if (btn._id, "click") in f.targets]
    return types.SimpleNamespace(demo=demo, dep=dep)


@pytest.fixture
def toasts(monkeypatch):
    """The message of every gr.Warning raised during the test."""
    shown = []

    def record(message="Warning issued.", *a, **k):
        shown.append(message)
    monkeypatch.setattr(gr, "Warning", record)
    return shown


@pytest.fixture
def pipes(monkeypatch):
    """Stub app.get_pipes (run_forge calls it before it checks the payload); records every call."""
    def install(gen_imgs=(), rescue_img=BAD):
        calls = {"gen": [], "rescue": []}

        def gen(*a, **k):
            calls["gen"].append((a, k))
            return list(gen_imgs)

        def rescue(*a, **k):
            calls["rescue"].append((a, k))
            return rescue_img
        monkeypatch.setattr(app, "get_pipes", lambda: {"gen": gen, "rescue": rescue})
        return calls
    return install


def call_handler(ui, style="None", payload=PAY, batch=1):
    return ui.dep.fn(payload, PROMPT, batch, 1.35, 25, 7, False, 1, "", None, 0.5, style,
                     progress=no_progress)


def process_api(ui, payload, style="None"):
    inputs = [payload, PROMPT, 1, 1.35, 25, 7, False, 1, "", None, 0.5, style]
    return asyncio.run(ui.demo.process_api(ui.dep, inputs, state=SessionState(ui.demo)))


# ---------------------------------------------------------------- the handler's error path (rows 1-5)
@pytest.mark.parametrize("style", [None, "Mosaic"])
@pytest.mark.parametrize("payload", ["", "   "])
def test_empty_payload_shows_in_the_report(ui, toasts, pipes, monkeypatch, style, payload):  # row 1
    archived = []
    monkeypatch.setattr(app, "archive_rejects", lambda r: archived.append(r) or "x")
    calls = pipes([GOOD])
    assert call_handler(ui, style, payload) == ([], report_for(EMPTY_MESSAGE), None)
    assert calls == {"gen": [], "rescue": []}
    assert archived == []  # §1: the error path does not reach the reject archive


@pytest.mark.parametrize("message", ["boom", 'it\'s "quoted"'])
def test_any_gr_error_from_forge_shows_verbatim(ui, toasts, monkeypatch, message):  # row 3
    monkeypatch.setattr(app, "forge", raiser(gr.Error(message)))
    assert call_handler(ui) == ([], report_for(message), None)


@pytest.mark.parametrize("payload, report", [
    ("", lambda: report_for(EMPTY_MESSAGE)),
    ("   ", lambda: report_for(EMPTY_MESSAGE)),
    (LONG_PAYLOAD, long_payload_report),
], ids=["empty", "blank", "long"])
def test_toast_repeats_the_report_once(ui, toasts, pipes, payload, report):  # row 4, rows 1-2
    pipes([GOOD])
    out = call_handler(ui, payload=payload)
    assert out[1] == report()
    assert toasts == [out[1]]


def test_toast_repeats_a_raised_gr_error_once(ui, toasts, monkeypatch):  # row 4, row 3
    monkeypatch.setattr(app, "forge", raiser(gr.Error("boom")))
    out = call_handler(ui)
    assert out[1] == "Couldn't forge: boom"
    assert toasts == [out[1]]


def test_toast_goes_through_the_real_gr_warning(ui, pipes):  # row 4: no event context, so a UserWarning
    pipes([GOOD])
    with pytest.warns(UserWarning) as caught:
        out = call_handler(ui, payload="")
    assert [str(w.message) for w in caught if "Couldn't forge" in str(w.message)] == [out[1]]


@pytest.mark.parametrize("exc", [RuntimeError("x"), ValueError("y"), PayloadError("z")],
                         ids=["runtime", "value", "payload"])
def test_other_exceptions_propagate_unchanged(ui, toasts, monkeypatch, exc):  # row 5
    monkeypatch.setattr(app, "forge", raiser(exc))
    with pytest.raises(type(exc)) as e:
        call_handler(ui)
    assert e.value is exc
    assert toasts == []


def test_style_resolution_stays_outside_the_handled_path(ui, toasts, monkeypatch):  # §1: apply_style
    exc = gr.Error("from style")
    forged = []
    monkeypatch.setattr(app, "apply_style", raiser(exc))
    monkeypatch.setattr(app, "forge", lambda *a, **k: forged.append(a))
    with pytest.raises(gr.Error) as e:
        call_handler(ui, "Mosaic")
    assert e.value is exc
    assert forged == []
    assert toasts == []


# ---------------------------------------------------------------- successful runs (rows 6-8)
def test_success_returns_forges_own_object(ui, toasts, monkeypatch):  # row 6
    sentinel = object()
    monkeypatch.setattr(app, "forge", lambda *a, **k: sentinel)
    assert call_handler(ui) is sentinel
    assert toasts == []


def test_normal_run_is_untouched(ui, toasts, pipes):  # row 7
    pipes([GOOD, BAD, BAD])
    survivors, report, control = call_handler(ui, batch=3)
    assert [im for im, _ in survivors] == [GOOD]
    assert report.startswith("1/3 passed")
    assert "Couldn't forge" not in report
    assert isinstance(control, Image.Image)
    assert toasts == []


def test_warn_band_payload_is_a_success(ui, toasts, pipes):  # row 8
    pipes([BAD])
    _, warn = normalize_payload(WARN_BAND_PAYLOAD)
    assert warn
    _, report, _ = call_handler(ui, payload=WARN_BAND_PAYLOAD)
    assert warn in report
    assert "Couldn't forge" not in report
    assert toasts == []


# ---------------------------------------------------------------- the real Gradio path (rows 9-10)
@pytest.mark.parametrize("payload, report", [
    ("", lambda: report_for(EMPTY_MESSAGE)),
    (LONG_PAYLOAD, long_payload_report),
], ids=["empty-row9", "long-row10"])
def test_gradio_path_shows_the_error(ui, toasts, pipes, payload, report):  # rows 9-10
    calls = pipes([GOOD])
    gallery, shown, control = process_api(ui, payload)["data"]
    assert not gallery
    assert shown == report()
    assert control is None
    assert calls["gen"] == []
    assert toasts == [shown]


# ---------------------------------------------------------------- what stays as it is (rows 13, 16)
def test_forge_itself_still_raises(toasts, pipes):  # row 13
    calls = pipes([GOOD])
    with pytest.raises(gr.Error) as e:
        app.forge("", PROMPT, 1, 1.35, 25, 7, False, 1)
    assert e.value.message == EMPTY_MESSAGE
    assert calls["gen"] == []
    assert toasts == []


def test_gate_line_and_error_wording_live_where_the_spec_says():  # row 16
    source = Path(app.__file__).read_text(encoding="utf-8")
    (gate,) = [line for line in source.splitlines() if "THE GATE" in line]
    assert gate.strip() == GATE_LINE
    in_ui = inspect.getsource(app.build_ui)
    assert "Couldn't forge" in in_ui
    assert source.count("Couldn't forge") == in_ui.count("Couldn't forge")
    assert "Couldn't forge" not in inspect.getsource(app.forge)
    assert "Couldn't forge" not in inspect.getsource(app.run_forge)
    assert not re.search(r"\bvalidate\b", in_ui)  # §1: no added line carries the token
