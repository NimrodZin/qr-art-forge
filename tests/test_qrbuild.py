import numpy as np
import pytest
import qrcode
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


def test_https_input_unchanged():
    assert normalize_payload("https://nimrodzin.com")[0] == "https://nimrodzin.com"


def test_dotted_text_with_space_stays_text():
    assert normalize_payload("hello world.txt")[0] == "hello world.txt"


def test_exactly_80_chars_accepted():
    p = "x" * 80
    assert normalize_payload(p)[0] == p


def test_81_chars_rejected():
    with pytest.raises(PayloadError):
        normalize_payload("x" * 81)


def test_none_rejected():
    with pytest.raises(PayloadError):
        normalize_payload(None)


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


def test_output_size_is_768():
    im = make_qr("https://nimrodzin.com")
    assert im.size == (768, 768)


def test_non_grey_bounding_box_is_centred():
    payload = "https://nimrodzin.com"
    im = make_qr(payload)
    arr = np.array(im)
    mask = np.any(arr != np.array(GREY), axis=-1)
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    top, bottom = rows[0], rows[-1]
    left, right = cols[0], cols[-1]
    assert left == pytest.approx(SIZE - 1 - right, abs=1)
    assert top == pytest.approx(SIZE - 1 - bottom, abs=1)


def test_non_grey_bounding_box_width_matches_module_grid():
    payload = "https://nimrodzin.com"
    im = make_qr(payload)
    arr = np.array(im)
    mask = np.any(arr != np.array(GREY), axis=-1)
    cols = np.where(mask.any(axis=0))[0]
    width = cols[-1] - cols[0] + 1

    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=4, box_size=1)
    q.add_data(payload)
    q.make(fit=True)
    n = q.modules_count + 8
    module = SIZE // n
    assert width == n * module


def test_quiet_zone_is_four_modules_from_grey_edge():
    payload = "https://nimrodzin.com"
    im = make_qr(payload)
    arr = np.array(im)
    mask = np.any(arr != np.array(GREY), axis=-1)
    cols = np.where(mask.any(axis=0))[0]
    left = cols[0]

    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=4, box_size=1)
    q.add_data(payload)
    q.make(fit=True)
    n = q.modules_count + 8
    module = SIZE // n

    centre = SIZE // 2
    px = im.load()
    x = left
    white_count = 0
    while px[x, centre] == (255, 255, 255):
        white_count += 1
        x += 1
    assert white_count == 4 * module
