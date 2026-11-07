"""Hard constraint: nothing unscannable reaches the gallery."""
import pytest
from PIL import Image
import app
import validator
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


# --- 02 v0.5: a thin candidate stays out of the gallery and stays rescue-eligible ---

THIN = {"full": 2, "small": 1, "tilt": 0}
SOLID = {"full": 3, "small": 3, "tilt": 3}
CANDIDATE = Image.new("RGB", (768, 768), (90, 90, 90))
RESCUED = Image.new("RGB", (768, 768), (91, 91, 91))


def _validate_with_hits(monkeypatch, counts_by_image):
    """app.validate = the real validator.validate, under a stub of D chosen per candidate."""
    def validate(im, payload):
        counts = counts_by_image[id(im)]
        real = validator._conditions
        names = {}

        def conditions(img):
            out = real(img)
            names.update({id(v): c for c, v in out.items()})
            return out
        with pytest.MonkeyPatch.context() as m:
            m.setattr(validator, "_conditions", conditions)
            m.setattr(validator, "_phone_hits",
                      lambda img, expected: ["LA@S0", "GH@S0", "FT@S0"][:counts[names[id(img)]]])
            return validator.validate(im, payload)
    monkeypatch.setattr(app, "validate", validate)


def _archived(monkeypatch):
    """Spy on what run_forge hands to the reject archive: (label, image, validate-result)."""
    seen = []
    real = app.build_reject_records

    def build(payload, settings, entries, *a, **k):
        seen.extend(entries)
        return real(payload, settings, entries, *a, **k)
    monkeypatch.setattr(app, "build_reject_records", build)
    return seen


def _forge_one_candidate(rescue, rescue_returns=None):
    calls = []
    pipes = {"gen": lambda *a, **k: [CANDIDATE],
             "rescue": lambda *a, **k: (calls.append(1), rescue_returns)[1]}
    surv, report, _ = app.run_forge(PAY, "p", 1, 1.35, 25, 7, rescue, 5, pipes=pipes)
    return surv, report, calls


def test_v5_thin_candidate_stays_out_of_the_gallery(monkeypatch):  # spec row 19
    _validate_with_hits(monkeypatch, {id(CANDIDATE): THIN})
    archived = _archived(monkeypatch)
    surv, report, calls = _forge_one_candidate(rescue=False)
    assert surv == [] and "0/1 passed" in report and calls == []
    ((label, im, v),) = archived
    assert label == "seed5" and im is CANDIDATE
    assert v["pass"] is False and v["thin"] is True


def test_v5_thin_candidate_is_rescued_and_only_the_rescue_survives(monkeypatch):  # spec row 20
    _validate_with_hits(monkeypatch, {id(CANDIDATE): THIN, id(RESCUED): SOLID})
    surv, report, calls = _forge_one_candidate(rescue=True, rescue_returns=RESCUED)
    assert calls == [1]
    assert len(surv) == 1 and surv[0][0] is RESCUED
    assert "→ rescue PASS" in report


def test_v5_thin_rescue_of_a_thin_candidate_is_dropped(monkeypatch):  # spec row 21
    _validate_with_hits(monkeypatch, {id(CANDIDATE): THIN, id(RESCUED): THIN})
    archived = _archived(monkeypatch)
    surv, report, calls = _forge_one_candidate(rescue=True, rescue_returns=RESCUED)
    assert calls == [1] and surv == []
    assert "→ rescue FAIL" in report
    assert [label for label, _, _ in archived] == ["seed5", "seed5-rescue"]
    assert archived[0][1] is CANDIDATE and archived[1][1] is RESCUED
    assert all(v["pass"] is False for _, _, v in archived)
