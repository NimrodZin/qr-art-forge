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
    monkeypatch.setattr(validator, "_zx_read", lambda img, binarizer: "")
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is False and v["score"] == 0


def test_zxing_miss_on_one_condition_fails(monkeypatch):
    real = validator._phone_decode
    calls = []

    def zx(img, expected):
        calls.append(img)
        return False if len(calls) == 2 else real(img, expected)  # full, small, tilt
    monkeypatch.setattr(validator, "_phone_decode", zx)
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is False and v["score"] == 2
    assert v["results"]["small"]["zx"] is False


def test_every_condition_is_softened(monkeypatch):
    # v0.3: softening moved into D. Per condition, D reads the unsoftened variant and
    # S_1, S_2 of it; after contrast x0.85 and +20, softened pixels lie in [20, 237].
    img = np.zeros((768, 768, 3), np.uint8)
    img[:, 384:] = 255
    seen = []
    monkeypatch.setattr(validator, "_zx_read", lambda im, b: (seen.append(im), "")[1])
    for name, variant in validator._conditions(img).items():
        seen.clear()
        assert validator._phone_decode(variant, PAY) is False
        distinct = list({id(im): im for im in seen}.values())
        assert len(distinct) == 3, name
        assert distinct[0] is variant, name
        for im in distinct[1:]:
            assert im.shape == variant.shape, name
            assert im.min() >= 20 and im.max() <= 237, name


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


# --- v0.3: phone-like decode D(img) = 3 binarizers x {img, S_1, S_2}, any-hit ---

import cv2
import pytest
import zxingcpp

BIN = zxingcpp.Binarizer


# (a)
@pytest.mark.parametrize("pay", [PAY, "https://example.org/a?b=1", "hello world"])
def test_v3_generated_clean_qr_passes_three_of_three(pay):
    v = validate(make_qr(pay), pay)
    assert v["pass"] is True and v["score"] == 3 and v["max"] == 3
    assert all(r["zx"] is True for r in v["results"].values())


# (b)
def test_v3_only_global_histogram_succeeds_still_passes(monkeypatch):
    seen = set()

    def zx(img, binarizer):
        seen.add(binarizer)
        return PAY if binarizer == BIN.GlobalHistogram else ""
    monkeypatch.setattr(validator, "_zx_read", zx)
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is True and v["score"] == 3
    assert BIN.GlobalHistogram in seen


# (c)
def test_v3_only_two_sigma_softened_variant_succeeds_still_passes(monkeypatch):
    real_soften = validator._soften
    two_sigma = []

    def soften(img, k):
        out = real_soften(img, k)
        if k == 2:
            two_sigma.append(out)
        return out

    def zx(img, binarizer):
        return PAY if any(img is o for o in two_sigma) else ""
    monkeypatch.setattr(validator, "_soften", soften)
    monkeypatch.setattr(validator, "_zx_read", zx)
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is True and v["score"] == 3
    assert len(two_sigma) == 3  # one S_2 per condition


# (d)
def test_v3_blank_scores_zero_after_all_nine_attempts(monkeypatch):
    real = validator._zx_read
    calls = []

    def zx(img, binarizer):
        calls.append(binarizer)
        return real(img, binarizer)
    monkeypatch.setattr(validator, "_zx_read", zx)
    v = validate(Image.new("RGB", (768, 768), (200, 200, 200)), PAY)
    assert v["pass"] is False and v["score"] == 0 and v["max"] == 3
    assert len(calls) == 27  # 3 conditions x 3 binarizers x 3 softening levels
    assert set(calls) == {BIN.LocalAverage, BIN.GlobalHistogram, BIN.FixedThreshold}


# (e)
def test_v3_wrong_payload_fails():
    v = validate(make_qr(PAY), "https://other.io")
    assert v["pass"] is False and v["score"] == 0


def test_v3_near_payload_is_not_a_hit(monkeypatch):
    # Exact string match only: prefix/suffix/case variants never count.
    for near in (PAY + "/", PAY[:-1], PAY.upper()):
        monkeypatch.setattr(validator, "_zx_read", lambda img, b, s=near: s)
        v = validate(make_qr(PAY), PAY)
        assert v["pass"] is False and v["score"] == 0, near


# (f)
def test_v3_results_keep_zx_and_cv_per_condition(monkeypatch):
    monkeypatch.setattr(validator, "_zx_read",
                        lambda img, b: PAY if b == BIN.FixedThreshold else "")
    v = validate(make_qr(PAY), PAY)
    assert set(v) == {"pass", "score", "max", "results"}
    assert set(v["results"]) == CONDS
    for r in v["results"].values():
        assert set(r) == {"zx", "cv"}
        assert type(r["zx"]) is bool and type(r["cv"]) is bool
    assert summary_line(v).startswith("PASS full zx✓ (cv")


def test_v3_conditions_are_unsoftened():
    img = np.zeros((768, 768, 3), np.uint8)
    img[:, 384:] = 255
    variants = validator._conditions(img)
    assert set(variants) == CONDS
    assert np.array_equal(variants["full"], img)
    assert max(variants["small"].shape[:2]) == 480
    assert variants["small"].min() == 0 and variants["small"].max() == 255
    assert variants["tilt"].shape == img.shape
    assert variants["tilt"][0, 0].tolist() == [255, 255, 255]  # white border
    assert variants["tilt"][384, 100].tolist() == [0, 0, 0]


@pytest.mark.parametrize("w,k,sigma", [(768, 1, 768 / 600), (768, 2, 2 * 768 / 600),
                                       (480, 1, 1.0), (480, 2, 2.0)])
def test_v3_soften_sigma_and_levels(w, k, sigma):
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (w, w, 3), dtype=np.uint8)
    want = cv2.convertScaleAbs(cv2.GaussianBlur(img, (0, 0), sigmaX=sigma), alpha=0.85, beta=20)
    assert np.array_equal(validator._soften(img, k), want)


def test_v3_soften_level_zero_is_contrast_brightness_only():
    img = np.zeros((600, 600, 3), np.uint8)
    img[:, 300:] = 255
    s0 = validator._soften(img, 0)
    assert np.array_equal(s0, cv2.convertScaleAbs(img, alpha=0.85, beta=20))
    assert s0.min() == 20 and s0.max() == 237


def test_v3_opencv_sees_the_unsoftened_variant(monkeypatch):
    seen = []
    monkeypatch.setattr(validator, "_decode_cv", lambda img: (seen.append(img), "")[1])
    img = make_qr(PAY)
    v = validate(img, PAY)
    assert v["pass"] is True and all(r["cv"] is False for r in v["results"].values())
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    assert np.array_equal(seen[0], bgr)  # full, exactly the candidate pixels


def test_v3_phone_decode_returns_early_on_first_hit(monkeypatch):
    calls = []
    monkeypatch.setattr(validator, "_zx_read", lambda img, b: (calls.append(b), PAY)[1])
    img = cv2.cvtColor(np.array(make_qr(PAY)), cv2.COLOR_RGB2BGR)
    assert validator._phone_decode(img, PAY) is True
    assert len(calls) == 1
