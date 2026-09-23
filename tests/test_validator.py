from PIL import Image
from qrbuild import make_qr
from validator import validate

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
