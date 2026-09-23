import numpy as np
from PIL import Image
import validator
from qrbuild import make_qr
from validator import validate, summary_line

PAY = "https://nimrodzin.com"
CONDS = {"full", "small", "tilt"}


def test_clean_qr_passes_all_three():
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is True
    assert v["max"] == 3
    assert v["score"] == 3


def test_wrong_payload_fails():
    v = validate(make_qr(PAY), "https://other.io")
    assert v["pass"] is False
    assert v["score"] == 0


def test_blank_fails_with_zero_score():
    v = validate(Image.new("RGB", (768, 768), (200, 200, 200)), PAY)
    assert v["pass"] is False and v["score"] == 0 and v["max"] == 3


def test_three_conditions_with_bool_zx_and_cv():
    v = validate(make_qr(PAY), PAY)
    assert set(v["results"]) == CONDS
    for r in v["results"].values():
        assert set(r) == {"zx", "cv"}
        assert type(r["zx"]) is bool and type(r["cv"]) is bool


def test_opencv_is_advisory_only(monkeypatch):
    monkeypatch.setattr(validator, "_decode_cv", lambda img: "")
    v = validate(make_qr(PAY), PAY)
    assert all(r["zx"] is True and r["cv"] is False for r in v["results"].values())
    assert v["pass"] is True and v["score"] == 3


def test_zxing_gates_even_when_opencv_reads(monkeypatch):
    monkeypatch.setattr(validator, "_decode_zx", lambda img: "")
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is False and v["score"] == 0


def test_zxing_miss_on_one_condition_fails(monkeypatch):
    real = validator._decode_zx
    calls = []

    def zx(img):
        calls.append(img)
        return "" if len(calls) == 2 else real(img)  # conditions run full, small, tilt
    monkeypatch.setattr(validator, "_decode_zx", zx)
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is False and v["score"] == 2
    assert v["results"]["small"]["zx"] is False


def test_every_condition_is_softened():
    # Pure black/white input: after contrast x0.85 and +20, every pixel lies in [20, 237].
    img = np.zeros((768, 768, 3), np.uint8)
    img[:, 384:] = 255
    variants = validator._conditions(img)
    assert set(variants) == CONDS
    for name, im in variants.items():
        assert im.min() >= 20, name
        assert im.max() <= 237, name
    assert max(variants["small"].shape[:2]) == 480
    assert variants["full"].shape == variants["tilt"].shape == img.shape


def test_summary_line_shows_cv_as_advisory():
    v = validate(make_qr(PAY), PAY)
    cv = {c: "✓" if r["cv"] else "✗" for c, r in v["results"].items()}
    assert summary_line(v) == (f"PASS full zx✓ (cv{cv['full']}) | small zx✓ (cv{cv['small']}) | "
                               f"tilt zx✓ (cv{cv['tilt']})  (3/3)")


def test_summary_line_mixed():
    v = {"pass": False, "score": 1, "max": 3,
         "results": {"full": {"zx": True, "cv": False},
                     "small": {"zx": False, "cv": True},
                     "tilt": {"zx": False, "cv": False}}}
    assert summary_line(v) == "FAIL full zx✓ (cv✗) | small zx✗ (cv✓) | tilt zx✗ (cv✗)  (1/3)"
