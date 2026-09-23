from PIL import Image
from qrbuild import make_qr
from validator import validate, summary_line

PAY = "https://nimrodzin.com"


def test_clean_qr_passes_all():
    v = validate(make_qr(PAY), PAY)
    assert v["pass"] is True
    assert v["score"] == v["max"]


def test_wrong_payload_fails():
    assert validate(make_qr(PAY), "https://other.io")["pass"] is False


def test_blank_fails_with_zero_score():
    v = validate(Image.new("RGB", (768, 768), (200, 200, 200)), PAY)
    assert v["pass"] is False and v["score"] == 0


def test_all_four_conditions_reported():
    v = validate(make_qr(PAY), PAY)
    assert set(v["results"]) == {"full", "small", "tilt", "soft"}


def test_summary_line_per_decoder_marks():
    v = validate(make_qr(PAY), PAY)
    assert summary_line(v) == ("PASS full cv✓ zx✓ | small cv✓ zx✓ | tilt cv✓ zx✓ | "
                               "soft cv✓ zx✓  (8/8)")


def test_summary_line_mixed_and_zx_missing():
    v = {"pass": False, "score": 2, "max": 5,
         "results": {"full": {"cv": True, "zx": False},
                     "small": {"cv": False, "zx": True},
                     "tilt": {"cv": True, "zx": None},
                     "soft": {"cv": False, "zx": None}}}
    assert summary_line(v) == ("FAIL full cv✓ zx✗ | small cv✗ zx✓ | tilt cv✓ | "
                               "soft cv✗  (2/5)")
