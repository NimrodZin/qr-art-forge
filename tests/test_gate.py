"""Hard constraint: nothing unscannable reaches the gallery."""
import pytest
from PIL import Image
import app
from qrbuild import make_qr

PAY = "nimrodzin.com"
GOOD = make_qr("https://" + PAY)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))


@pytest.fixture(autouse=True)
def no_archive_env(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)


def fake_pipes(rescue_returns):
    return {
        "gen": lambda *a, **k: [GOOD, BAD, BAD],
        "rescue": lambda *a, **k: rescue_returns,
    }


def test_only_survivors_in_gallery():
    surv, report, ctrl = app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1, pipes=fake_pipes(BAD))
    assert len(surv) == 1
    assert surv[0][0] is GOOD
    assert "1/3 passed" in report


def test_rescue_cannot_smuggle_a_failure():
    surv, *_ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, True, 1, pipes=fake_pipes(BAD))
    assert len(surv) == 1


def test_rescue_only_for_near_misses():
    calls = []
    pipes = fake_pipes(GOOD)
    pipes["rescue"] = lambda *a, **k: (calls.append(1), GOOD)[1]
    surv, *_ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, True, 1, pipes=pipes)
    # BAD scores 0 → not eligible, so rescue is never invoked
    assert calls == []
    assert len(surv) == 1


def test_report_shows_encoded_payload():
    _, report, _ = app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=fake_pipes(BAD))
    assert "Encoded: https://nimrodzin.com" in report


def test_rejects_never_enter_gallery_and_archive_line_is_last():
    surv, report, _ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, True, 1, pipes=fake_pipes(BAD))
    assert all(im is not BAD for im, _ in surv)
    assert report.splitlines()[-1] == "rejects not archived (HF_TOKEN/REJECTS_REPO unset)"


def _near_miss(score):
    return {"pass": False, "score": score, "max": 3,
            "results": {c: {"zx": i < score, "cv": False}
                        for i, c in enumerate(("full", "small", "tilt"))}}


@pytest.mark.parametrize("score,rescued", [(0, False), (1, True), (2, True)])
def test_rescue_eligibility_is_score_at_least_one(monkeypatch, score, rescued):
    calls = []
    real_validate = app.validate
    monkeypatch.setattr(app, "validate",
                        lambda im, p: _near_miss(score) if im is BAD else real_validate(im, p))
    pipes = {"gen": lambda *a, **k: [BAD],
             "rescue": lambda *a, **k: (calls.append(1), GOOD)[1]}
    surv, *_ = app.run_forge(PAY, "p", 1, 1.35, 25, 7, True, 1, pipes=pipes)
    assert (calls == [1]) is rescued
    assert len(surv) == int(rescued)


def test_validate_max_is_three():
    assert app.validate(GOOD, "https://" + PAY)["max"] == 3
    assert app.validate(BAD, "https://" + PAY)["max"] == 3


def test_ui_intro_states_three_conditions():
    import gradio as gr
    demo = app.build_ui()
    texts = [b.value for b in demo.blocks.values() if isinstance(b, gr.Markdown)]
    assert any("Every result shown has been read by a phone-grade decoder under three scan "
               "conditions." in t for t in texts)


def _gallery(demo):
    import gradio as gr
    (g,) = [b for b in demo.blocks.values() if isinstance(b, gr.Gallery)]
    return g


def test_gallery_serves_png():
    assert _gallery(app.build_ui()).format == "png"


def test_served_pixels_are_validated_pixels(tmp_path):
    import numpy as np
    pipes = {"gen": lambda *a, **k: [GOOD], "rescue": lambda *a, **k: BAD}
    surv, *_ = app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes)
    assert len(surv) == 1 and app.validate(surv[0][0], "https://" + PAY)["pass"]
    g = _gallery(app.build_ui())
    g.GRADIO_CACHE = str(tmp_path)  # encode exactly as Gradio will when serving the gallery
    (served,) = g.postprocess(surv).root
    decoded = np.array(Image.open(served.image.path).convert("RGB"))
    assert np.array_equal(decoded, np.array(surv[0][0].convert("RGB")))
