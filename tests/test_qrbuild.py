import pytest
from qrbuild import normalize_payload, make_qr, PayloadError, SIZE, GREY


def test_bare_domain_gets_https():
    assert normalize_payload("nimrodzin.com")[0] == "https://nimrodzin.com"


def test_scheme_kept():
    assert normalize_payload(" http://x.io/a ")[0] == "http://x.io/a"


def test_plain_text_unchanged():
    assert normalize_payload("hello world")[0] == "hello world"


def test_empty_rejected():
    with pytest.raises(PayloadError):
        normalize_payload("   ")


def test_over_80_rejected():
    with pytest.raises(PayloadError):
        normalize_payload("x" * 81)


def test_over_40_warns_under_40_does_not():
    assert normalize_payload("x" * 41)[1] is not None
    assert normalize_payload("x" * 40)[1] is None


def test_control_image_geometry():
    im = make_qr("https://nimrodzin.com")
    assert im.size == (SIZE, SIZE)
    assert im.getpixel((0, 0)) == GREY            # grey canvas corner
    px = im.load()
    # quiet zone: a white ring exists inside the grey border
    centre = SIZE // 2
    row = [px[x, centre] for x in range(SIZE)]
    assert (255, 255, 255) in row and (0, 0, 0) in row
