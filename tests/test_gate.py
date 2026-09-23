"""Hard constraint: nothing unscannable reaches the gallery."""
from PIL import Image
import app
from qrbuild import make_qr

PAY = "nimrodzin.com"
GOOD = make_qr("https://" + PAY)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))


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
