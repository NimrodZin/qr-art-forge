"""Shadow-style centre repair (OD 12 step 2). See steps/m2-12/spec.md.

Corrects lightness only, in small soft dots at module centres the candidate gets wrong.
It never sees the payload or the decoder: the module grid comes from the control image's
pixels, and the repaired image goes through validate() like any other candidate.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import qrcode.util
from PIL import Image

WINDOW = 3        # modules, side of the threshold window
CENTRE = 0.15     # centre-sample radius, fraction of a module
RADIUS = 0.3      # dot core radius, fraction of a module
FEATHER = 0.2     # Gaussian sigma, fraction of a module
SUPPORT = RADIUS + 3 * FEATHER
MARGIN = 0.15     # OKLab L units, 0..1

QUIET = 4         # quiet-zone modules, as in qrbuild.make_qr
TOL = 1e-6        # flag-comparison float tolerance: sRGB white is L 0.9999999935 with these
                  # matrices, so a white centre must not count as "below the ceiling 1"


def repair_enabled(env: Mapping[str, str] | None = None) -> bool:
    """On by default; QRAF_REPAIR=0 disables (same pattern as QRAF_VAE_SLICING)."""
    if env is None:
        env = os.environ
    return env.get("QRAF_REPAIR") != "0"


# ---------------------------------------------------------------- OKLab (Ottosson 2020)
_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])
_M1_INV = np.linalg.inv(_M1)
_M2_INV = np.linalg.inv(_M2)


def to_oklab(rgb: np.ndarray) -> np.ndarray:
    """uint8 sRGB (..., 3) → float64 OKLab (..., 3)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return np.cbrt(lin @ _M1.T) @ _M2.T


def from_oklab(lab: np.ndarray) -> np.ndarray:
    """float64 OKLab (..., 3) → uint8 sRGB; linear RGB clipped to [0, 1], rounded to nearest."""
    lin = np.clip((np.asarray(lab, dtype=np.float64) @ _M2_INV.T) ** 3 @ _M1_INV.T, 0.0, 1.0)
    c = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(np.rint(c * 255.0), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- module grid
@dataclass(frozen=True)
class Grid:
    module: int        # px per module
    offset: int        # px from the canvas edge to the symbol (quiet zone included)
    n: int             # modules per side, quiet zone included
    version: int
    dark: np.ndarray   # bool n×n


def module_grid(control: Image.Image) -> Grid:
    """Read the module grid back from a make_qr control image. Raises ValueError if it is not one."""
    a = np.asarray(control.convert("RGB"))
    h, w, _ = a.shape
    if h != w:
        raise ValueError("control image is not square")
    ink = (a != 128).any(axis=2)  # the symbol: white quiet zone and modules on the grey canvas
    rows, cols = np.nonzero(ink.any(axis=1))[0], np.nonzero(ink.any(axis=0))[0]
    if rows.size == 0:
        raise ValueError("control image has no QR symbol")
    offset, side = int(rows[0]), int(rows[-1]) - int(rows[0]) + 1
    if int(cols[0]) != offset or int(cols[-1]) - int(cols[0]) + 1 != side:
        raise ValueError("control symbol is not a centred square")
    black = (a == 0).all(axis=2)
    first_dark = np.nonzero(black[:, offset:offset + side].any(axis=1))[0]
    if first_dark.size == 0 or (int(first_dark[0]) - offset) % QUIET:
        raise ValueError("control symbol has no quiet zone")
    module = (int(first_dark[0]) - offset) // QUIET
    if module < 1 or side % module:
        raise ValueError("control symbol does not tile into modules")
    n = side // module
    version = (n - 2 * QUIET - 17) // 4  # modules_count = 4 * version + 17
    if (n - 2 * QUIET - 17) % 4 or not 1 <= version <= 40 or module != w // n \
            or offset != (w - side) // 2:
        raise ValueError("control symbol size does not match a QR version")
    centres = offset + module // 2 + module * np.arange(n)
    px = a[np.ix_(centres, centres)]
    dark = (px == 0).all(axis=2)
    if not (dark | (px == 255).all(axis=2)).all():
        raise ValueError("control symbol modules are not black and white")
    return Grid(module=module, offset=offset, n=n, version=version, dark=dark)


def skip_mask(grid: Grid) -> np.ndarray:
    """bool n×n: quiet zone, finders with their separators, alignment patterns."""
    n, q = grid.n, QUIET
    s = np.zeros((n, n), bool)
    s[:q, :] = s[-q:, :] = s[:, :q] = s[:, -q:] = True
    for r0, c0 in ((q, q), (q, n - q - 8), (n - q - 8, q)):
        s[r0:r0 + 8, c0:c0 + 8] = True
    pos = qrcode.util.pattern_position(grid.version)
    if pos:
        corners = {(pos[0], pos[0]), (pos[0], pos[-1]), (pos[-1], pos[0])}
        for r in pos:
            for c in pos:
                if (r, c) not in corners:
                    s[r + q - 2:r + q + 3, c + q - 2:c + q + 3] = True
    return s


# ---------------------------------------------------------------- repair
def repair(image: Image.Image, control: Image.Image) -> tuple[Image.Image, int]:
    """Return (repaired copy, modules touched). Lightness only; the input is never mutated."""
    if image.size != control.size:
        raise ValueError(f"image is {image.size}, control is {control.size}")
    grid = module_grid(control)
    skip = skip_mask(grid)
    m, off = grid.module, grid.offset
    rgb = np.array(image.convert("RGB"))
    lab = to_oklab(rgb)
    L = lab[..., 0]
    h, w = L.shape

    # threshold: mean L over a WINDOW×WINDOW-module square around each centre (integral image)
    ii = np.zeros((h + 1, w + 1))
    ii[1:, 1:] = L.cumsum(axis=0).cumsum(axis=1)
    half = (WINDOW // 2) * m

    rc = max(CENTRE * m, 0.71)
    reach = int(np.ceil(SUPPORT * m)) + 1
    dot_r, dot_s, sigma = RADIUS * m, SUPPORT * m, FEATHER * m

    D = np.zeros_like(L)          # darkening field
    U = np.zeros_like(L)          # lightening field
    Z = np.zeros((h, w), bool)    # dark zone: never brightened
    k = 0
    for r in range(grid.n):
        for c in range(grid.n):
            if skip[r, c]:
                continue
            cx, cy = off + (c + 0.5) * m, off + (r + 0.5) * m
            x0, y0 = max(0, off + c * m - half), max(0, off + r * m - half)
            x1, y1 = min(w, off + (c + 1) * m + half), min(h, off + (r + 1) * m + half)
            T = (ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]) / ((x1 - x0) * (y1 - y0))

            px0, py0 = max(0, int(cx) - reach), max(0, int(cy) - reach)
            px1, py1 = min(w, int(cx) + reach + 1), min(h, int(cy) + reach + 1)
            yy, xx = np.mgrid[py0:py1, px0:px1]
            d = np.hypot(xx + 0.5 - cx, yy + 0.5 - cy)
            patch = L[py0:py1, px0:px1]
            Lc = patch[d <= rc].mean()

            if grid.dark[r, c]:
                t = max(0.0, T - MARGIN)
                if not Lc > t + TOL:
                    continue
            else:
                t = min(1.0, T + MARGIN)
                if not Lc < t - TOL:
                    continue
            k += 1

            wgt = np.where(d <= dot_r, 1.0,
                           np.where(d < dot_s, np.exp(-(d - dot_r) ** 2 / (2 * sigma ** 2)), 0.0))
            win = (slice(py0, py1), slice(px0, px1))
            if grid.dark[r, c]:
                np.maximum(D[win], wgt * np.maximum(0.0, patch - t), out=D[win])
                Z[win] |= d < dot_s
            else:
                np.maximum(U[win], wgt * np.maximum(0.0, t - patch), out=U[win])

    delta = np.where(Z, -D, U)
    # skipped cells are never changed
    cells = np.zeros((h, w), bool)
    cells[off:off + grid.n * m, off:off + grid.n * m] = np.kron(skip, np.ones((m, m), bool))
    delta[cells] = 0.0

    out = rgb.copy()
    changed = delta != 0.0
    if changed.any():
        lab_c = lab[changed]
        lab_c[:, 0] += delta[changed]
        out[changed] = from_oklab(lab_c)
    return Image.fromarray(out, "RGB"), k
