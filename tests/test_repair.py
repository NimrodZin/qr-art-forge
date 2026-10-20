"""m2-12: shadow-style centre repair, pure module. Rows refer to steps/m2-12/spec.md §2 (P0–P13)."""
import ast
import functools
import importlib
import math
import pathlib

import numpy as np
import pytest
import qrcode
import qrcode.util
from PIL import Image

from qrbuild import make_qr
from validator import validate

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAY = "https://nimrodzin.com"
LONG = "https://example.com/" + "a" * 60  # 80 characters
assert len(LONG) == 80
PAYLOADS = ["abc", PAY, LONG]


def rp():
    """The module under test; imported per test so each test fails on its own while it is missing."""
    return importlib.import_module("repair")


# ---------------------------------------------------------------- independent OKLab L (Ottosson 2020)
_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])


def lab(rgb):
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return np.cbrt(lin @ _M1.T) @ _M2.T


def arr(im):
    return np.asarray(im.convert("RGB"))


# ---------------------------------------------------------------- reference geometry from qrcode itself
def qr_info(payload):
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=4)
    q.add_data(payload)
    q.make(fit=True)
    matrix = np.array(q.get_matrix(), dtype=bool)
    n = q.modules_count + 8
    module = 768 // n
    offset = (768 - n * module) // 2
    return {"version": q.version, "n": n, "module": module, "offset": offset, "dark": matrix}


def expected_skip(info):
    n = info["n"]
    s = np.zeros((n, n), bool)
    s[:4, :] = True
    s[-4:, :] = True
    s[:, :4] = True
    s[:, -4:] = True
    for r0, c0 in ((4, 4), (4, n - 12), (n - 12, 4)):
        s[r0:r0 + 8, c0:c0 + 8] = True
    pos = qrcode.util.pattern_position(info["version"])
    corners = set()
    if pos:
        corners = {(pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])}
    for r in pos:
        for c in pos:
            if (r, c) in corners:
                continue
            s[r + 4 - 2:r + 4 + 3, c + 4 - 2:c + 4 + 3] = True
    return s


C = make_qr(PAY)
INFO = qr_info(PAY)
M = INFO["module"]
OFF = INFO["offset"]
N = INFO["n"]
SKIP = expected_skip(INFO)
DARK = INFO["dark"]
def centre(r, c):
    return OFF + (c + 0.5) * M, OFF + (r + 0.5) * M


def disc(r, c, radius, strict=False):
    """Full-size mask of pixels whose centre is within `radius` px of module (r, c)'s centre."""
    cx, cy = centre(r, c)
    x0, x1 = max(0, int(cx - radius) - 1), min(768, int(cx + radius) + 2)
    y0, y1 = max(0, int(cy - radius) - 1), min(768, int(cy + radius) + 2)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy)
    mask = np.zeros((768, 768), bool)
    mask[y0:y1, x0:x1] = d < radius if strict else d <= radius
    return mask


def nearest_pixels(r, c):
    """The 1-4 pixels whose centres are nearest the module centre."""
    cx, cy = centre(r, c)
    xs = sorted({math.floor(cx - 0.5), math.ceil(cx - 0.5)})
    ys = sorted({math.floor(cy - 0.5), math.ceil(cy - 0.5)})
    return [(y, x) for y in ys for x in xs]


def cell_mask(cells):
    mask = np.zeros((768, 768), bool)
    for r, c in cells:
        mask[OFF + r * M:OFF + (r + 1) * M, OFF + c * M:OFF + (c + 1) * M] = True
    return mask


def outside_symbol_mask():
    mask = np.ones((768, 768), bool)
    mask[OFF:OFF + N * M, OFF:OFF + N * M] = False
    return mask


def data_modules():
    return [(r, c) for r in range(N) for c in range(N) if not SKIP[r, c]]


def expected_flags(L, modules):
    """§1 flagging rule, computed independently on lightness array L."""
    flagged = []
    rc = max(0.15 * M, 0.71)
    for r, c in modules:
        x0, y0 = OFF + (c - 1) * M, OFF + (r - 1) * M  # 3-module window, pixel-aligned
        T = L[max(0, y0):y0 + 3 * M, max(0, x0):x0 + 3 * M].mean()
        Lc = L[disc(r, c, rc)].mean()
        if DARK[r, c]:
            t = max(0.0, T - 0.15)
            hit, margin = Lc > t, abs(Lc - t)
        else:
            t = min(1.0, T + 0.15)
            hit, margin = Lc < t, abs(Lc - t)
        flagged.append(((r, c), hit, margin, t))
    return flagged


# ---------------------------------------------------------------- fixtures
FLAT = Image.new("RGB", (768, 768), (128, 128, 128))
L_GREY = lab(np.array([128, 128, 128]))[0]


@functools.lru_cache(maxsize=None)
def _p7():
    a = arr(C).copy()
    L = lab(a)[..., 0]
    chosen = []
    quota = {(True, True): 3, (True, False): 3, (False, True): 3, (False, False): 3}
    taken = np.zeros((N, N), bool)
    for r, c in data_modules():
        if taken[max(0, r - 4):r + 5, max(0, c - 4):c + 5].any():
            continue
        cell = (slice(OFF + r * M, OFF + (r + 1) * M), slice(OFF + c * M, OFF + (c + 1) * M))
        trial = L.copy()
        trial[cell] = L_GREY
        (_, hit, margin, _), = expected_flags(trial, [(r, c)])
        key = (bool(DARK[r, c]), bool(hit))
        if margin < 0.05 or quota[key] == 0:
            continue
        quota[key] -= 1
        chosen.append(((r, c), hit))
        taken[r, c] = True
        a[cell] = 128
        L = trial
    return a.tobytes(), tuple(chosen)


def p7_fixture():
    """C with flat grey (128) painted over chosen, well-separated data modules.

    Chosen so the flag decision is clear of the threshold by >= 0.05, and both flagged and
    unflagged painted modules occur. Returns (image, [((r, c), expected_flag), ...]).
    """
    raw, chosen = _p7()
    return Image.frombytes("RGB", (768, 768), raw), list(chosen)


# P13 recipe (recorded): the spec's default, unchanged — every non-skipped data module with
# (r*7 + c*3) % 3 == 0 (i.e. every third row), a disc of radius 0.2*m at its centre in the
# opposite colour. Checked against a throwaway reference outside the repo: the fixture fails
# validate() and the repaired image passes.
P13_RADIUS = 0.2


def p13_subset():
    return [(r, c) for r, c in data_modules() if (r * 7 + c * 3) % 3 == 0]


def p13_fixture():
    a = arr(C).copy()
    for r, c in p13_subset():
        a[disc(r, c, P13_RADIUS * M)] = 255 if DARK[r, c] else 0
    return Image.fromarray(a, "RGB")


# ---------------------------------------------------------------- P0
def test_p0_constants():
    m = rp()
    assert m.WINDOW == 3
    assert m.CENTRE == 0.15
    assert m.RADIUS == 0.3
    assert m.FEATHER == 0.2
    assert m.MARGIN == 0.15
    assert m.SUPPORT == m.RADIUS + 3 * m.FEATHER
    assert m.SUPPORT == pytest.approx(0.9)


def test_p0_repair_cannot_see_the_decoder():
    rp()
    tree = ast.parse((ROOT / "repair.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"validator", "zxingcpp", "cv2", "torch", "diffusers"}


def test_p0_repair_never_receives_the_payload():
    import inspect
    assert len(inspect.signature(rp().repair).parameters) == 2


# ---------------------------------------------------------------- P1
@pytest.mark.parametrize("payload", PAYLOADS)
def test_p1_module_grid_matches_qrcode(payload):
    info = qr_info(payload)
    g = rp().module_grid(make_qr(payload))
    assert g.n == info["n"]
    assert g.module == 768 // g.n == info["module"]
    assert g.offset == (768 - g.n * g.module) // 2 == info["offset"]
    assert g.version == info["version"]
    dark = np.asarray(g.dark, dtype=bool)
    assert dark.shape == (g.n, g.n)
    assert np.array_equal(dark, info["dark"])
    # the three payloads cover v1, v3 and a long (80-char) code
    assert {"abc": info["version"] == 1, PAY: info["version"] == 3,
            LONG: info["version"] > 3}[payload]


# ---------------------------------------------------------------- P2
@pytest.mark.parametrize("payload", PAYLOADS)
def test_p2_skip_mask(payload):
    m = rp()
    info = qr_info(payload)
    got = np.asarray(m.skip_mask(m.module_grid(make_qr(payload))), dtype=bool)
    assert got.shape == (info["n"], info["n"])
    assert np.array_equal(got, expected_skip(info))


def test_p2_version_1_has_no_alignment_pattern():
    m = rp()
    info = qr_info("abc")
    got = np.asarray(m.skip_mask(m.module_grid(make_qr("abc"))), dtype=bool)
    n = info["n"]
    only_finders = np.zeros((n, n), bool)
    only_finders[:4, :] = only_finders[-4:, :] = only_finders[:, :4] = only_finders[:, -4:] = True
    for r0, c0 in ((4, 4), (4, n - 12), (n - 12, 4)):
        only_finders[r0:r0 + 8, c0:c0 + 8] = True
    assert np.array_equal(got, only_finders)


# ---------------------------------------------------------------- P3
def test_p3_white_black_grey():
    m = rp()
    w = m.to_oklab(np.full((1, 1, 3), 255, np.uint8))
    assert w.dtype == np.float64 and w.shape == (1, 1, 3)
    assert w[0, 0, 0] == pytest.approx(1.0, abs=1e-3)
    assert abs(w[0, 0, 1]) <= 1e-3 and abs(w[0, 0, 2]) <= 1e-3
    b = m.to_oklab(np.zeros((1, 1, 3), np.uint8))
    assert np.allclose(b, 0, atol=1e-6)
    g = m.to_oklab(np.full((1, 1, 3), 128, np.uint8))
    assert g[0, 0, 0] == pytest.approx(0.600, abs=0.002)


def test_p3_round_trip():
    m = rp()
    greys = np.repeat(np.arange(256, dtype=np.uint8)[None, :, None], 3, axis=2)
    rnd = np.random.default_rng(1234).integers(0, 256, size=(1, 1000, 3), dtype=np.uint8)
    for rgb in (greys, rnd):
        back = m.from_oklab(m.to_oklab(rgb))
        assert back.dtype == np.uint8 and back.shape == rgb.shape
        assert np.abs(back.astype(int) - rgb.astype(int)).max() <= 1


def test_p3_matches_ottosson():
    rnd = np.random.default_rng(7).integers(0, 256, size=(4, 50, 3), dtype=np.uint8)
    assert np.allclose(rp().to_oklab(rnd), lab(rnd), atol=1e-6)


# ---------------------------------------------------------------- P4
def test_p4_clean_code_is_untouched():
    out, k = rp().repair(C, C)
    assert k == 0
    assert out.tobytes() == C.convert("RGB").tobytes()


# ---------------------------------------------------------------- P5
def test_p5_pure_and_deterministic():
    x, _ = p7_fixture()
    before = x.tobytes()
    out1, k1 = rp().repair(x, C)
    out2, k2 = rp().repair(x, C)
    assert x.tobytes() == before
    assert out1 is not x
    assert out1.tobytes() == out2.tobytes() and k1 == k2
    assert out1.mode == "RGB" and out1.size == x.size


# ---------------------------------------------------------------- P6
@functools.lru_cache(maxsize=None)
def _flat():
    out, k = rp().repair(FLAT, C)
    return out.tobytes(), k


def flat_result():
    raw, k = _flat()
    return Image.frombytes("RGB", (768, 768), raw), k


def test_p6_flat_grey_flags_every_data_module():
    _, k = flat_result()
    assert k == int((~SKIP).sum())


def test_p6_skipped_cells_and_outside_unchanged():
    out, _ = flat_result()
    o, i = arr(out), arr(FLAT)
    mask = cell_mask(zip(*np.nonzero(SKIP))) | outside_symbol_mask()
    assert np.array_equal(o[mask], i[mask])


def test_p6_centres_land_on_threshold_plus_minus_margin():
    out, _ = flat_result()
    Lout = lab(arr(out))[..., 0]
    T = lab(np.array([128, 128, 128]))[0]
    for r, c in data_modules():
        want = T - 0.15 if DARK[r, c] else T + 0.15
        for y, x in nearest_pixels(r, c):
            assert Lout[y, x] == pytest.approx(want, abs=0.01), (r, c, bool(DARK[r, c]))


# ---------------------------------------------------------------- P7
def test_p7_flagging_follows_the_rule():
    x, chosen = p7_fixture()
    hits = [rc for rc, hit in chosen if hit]
    assert hits and len(hits) < len(chosen), "fixture must mix flagged and unflagged modules"
    out, k = rp().repair(x, C)
    assert k == len(hits)
    near = np.zeros((768, 768), bool)
    for r, c in hits:
        near |= disc(r, c, 0.9 * M)
    assert np.array_equal(arr(out)[~near], arr(x)[~near])


# ---------------------------------------------------------------- P8 / P9
def _flagged_dark_light():
    x, chosen = p7_fixture()
    hits = [rc for rc, hit in chosen if hit]
    return [(FLAT, data_modules()), (x, hits)]


def test_p8_no_brightening_around_a_repaired_dark_centre():
    for img, flagged in _flagged_dark_light():
        out, _ = rp().repair(img, C)
        Lin, Lout = lab(arr(img))[..., 0], lab(arr(out))[..., 0]
        dark = [rc for rc in flagged if DARK[rc]]
        assert dark
        zone = np.zeros((768, 768), bool)
        for r, c in dark:
            zone |= disc(r, c, 0.9 * M, strict=True)
        assert (Lout[zone] <= Lin[zone] + 0.01).all()


def test_p9_light_cores_never_darken():
    for img, flagged in _flagged_dark_light():
        out, _ = rp().repair(img, C)
        Lin, Lout = lab(arr(img))[..., 0], lab(arr(out))[..., 0]
        dark_zone = np.zeros((768, 768), bool)
        for r, c in flagged:
            if DARK[r, c]:
                dark_zone |= disc(r, c, 0.9 * M, strict=True)
        light = [rc for rc in flagged if not DARK[rc]]
        assert light
        core = np.zeros((768, 768), bool)
        for r, c in light:
            core |= disc(r, c, 0.3 * M)
        core &= ~dark_zone
        assert core.any()
        assert (Lout[core] >= Lin[core] - 0.01).all()


# ---------------------------------------------------------------- P10
def test_p10_neutral_stays_neutral():
    out, _ = flat_result()
    o = arr(out).astype(int)
    changed = (o != arr(FLAT).astype(int)).any(axis=2)
    assert changed.any()
    px = o[changed]
    assert (px[:, 0] == px[:, 1]).all() and (px[:, 1] == px[:, 2]).all()


COLOURS = [(150, 112, 100), (100, 128, 150), (124, 138, 102), (140, 118, 140), (130, 130, 112)]


def test_p10_chroma_untouched():
    stripes = np.zeros((768, 768, 3), np.uint8)
    for i in range(768 // 37 + 1):
        stripes[:, i * 37:(i + 1) * 37] = COLOURS[i % len(COLOURS)]
    lab_in = lab(stripes)
    assert np.abs(lab_in[..., 1:]).max() <= 0.08
    img = Image.fromarray(stripes, "RGB")
    out, k = rp().repair(img, C)
    assert k > 0
    o = arr(out)
    changed = (o != stripes).any(axis=2)
    assert changed.any()
    assert o[changed].min() > 0 and o[changed].max() < 255, "fixture must stay in gamut"
    d = np.abs(lab(o)[..., 1:] - lab_in[..., 1:])[changed]
    assert d.max() <= 0.02


# ---------------------------------------------------------------- P11
def test_p11_size_mismatch_raises():
    with pytest.raises(ValueError):
        rp().repair(Image.new("RGB", (512, 512), (128, 128, 128)), C)


def test_p11b_grid_of_flat_grey_raises():
    with pytest.raises(ValueError):
        rp().module_grid(Image.new("RGB", (768, 768), (128, 128, 128)))


# ---------------------------------------------------------------- P12
@pytest.mark.parametrize("env,want", [({}, True), ({"QRAF_REPAIR": "1"}, True),
                                      ({"QRAF_REPAIR": "x"}, True), ({"QRAF_REPAIR": "0"}, False)])
def test_p12_repair_enabled(env, want):
    assert rp().repair_enabled(env) is want


def test_p12_reads_os_environ_at_call_time(monkeypatch):
    m = rp()
    monkeypatch.delenv("QRAF_REPAIR", raising=False)
    assert m.repair_enabled() is True
    monkeypatch.setenv("QRAF_REPAIR", "0")
    assert m.repair_enabled() is False
    monkeypatch.setenv("QRAF_REPAIR", "1")
    assert m.repair_enabled() is True


# ---------------------------------------------------------------- P13
def test_p13_repair_makes_damaged_code_pass():
    fixture = p13_fixture()
    assert validate(fixture, PAY)["pass"] is False  # precondition: the damage breaks the gate
    out, k = rp().repair(fixture, C)
    assert k == len(p13_subset())
    assert validate(out, PAY)["pass"] is True
