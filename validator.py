"""Scan validation for aesthetic QR codes (docs/02 v0.4).

A candidate passes only if the phone-like decode D succeeds on `full` and
`small`; `tilt` is still computed, reported and scored, but does not gate.
D = zxing-cpp with three binarizers on the variant and on two softened copies
of it; any exact hit counts, and every combo is tried so the report can list
the ones that hit. OpenCV is run on the unsoftened variant and reported as
advisory only.
"""
from __future__ import annotations
import numpy as np
import cv2
from PIL import Image

try:
    import zxingcpp
    HAVE_ZXING = True
    BINARIZERS = (zxingcpp.Binarizer.LocalAverage,
                  zxingcpp.Binarizer.GlobalHistogram,
                  zxingcpp.Binarizer.FixedThreshold)
except Exception:  # pragma: no cover
    HAVE_ZXING = False
    BINARIZERS = ()

SOFTEN_LEVELS = (1, 2)  # D runs on img, S_1(img), S_2(img)
GATES = ("full", "small")  # 02 v0.4: tilt is scored and reported, never gates
_BIN_CODE = dict(zip(BINARIZERS, ("LA", "GH", "FT")))  # hit "LA@S2", as local/f1_batch.py

_cv_det = cv2.QRCodeDetector()


def _decode_cv(img: np.ndarray) -> str:
    data, _, _ = _cv_det.detectAndDecode(img)
    return data or ""


def _zx_read(img: np.ndarray, binarizer) -> str:
    if not HAVE_ZXING:
        return ""
    res = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode,
                                 binarizer=binarizer)
    return res[0].text if res else ""


def _soften(img: np.ndarray, k: int) -> np.ndarray:
    """S_k(img): phone optics — blur σ = k·max(1, w/600), then contrast x0.85, brightness +20.

    S_0 is contrast/brightness only (no blur).
    """
    if k > 0:
        w = img.shape[1]
        img = cv2.GaussianBlur(img, (0, 0), sigmaX=k * max(1.0, w / 600))
    return cv2.convertScaleAbs(img, alpha=0.85, beta=20)


def _phone_hits(img: np.ndarray, expected: str) -> list[str]:
    """D(img), unrolled: every binarizer@softening combo on img, S_1(img), S_2(img) that reads exactly `expected`.

    D succeeds iff the list is non-empty. Order: S_0, S_1, S_2, each in BINARIZERS order, e.g. ["LA@S0", "GH@S2"].
    """
    hits = []
    for level in (0, *SOFTEN_LEVELS):
        variant = img if level == 0 else _soften(img, level)
        for binarizer in BINARIZERS:
            if _zx_read(variant, binarizer) == expected:
                hits.append(f"{_BIN_CODE[binarizer]}@S{level}")
    return hits


def _conditions(img: np.ndarray) -> dict[str, np.ndarray]:
    """Unsoftened condition variants of the exact candidate pixels."""
    h, w = img.shape[:2]
    out = {"full": img}

    # Phone-camera-ish downscale
    s = 480 / max(h, w)
    out["small"] = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

    # Mild perspective (hand-held tilt)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * 0.06, h * 0.04], [w * 0.94, 0], [w, h], [0, h * 0.97]])
    M = cv2.getPerspectiveTransform(src, dst)
    out["tilt"] = cv2.warpPerspective(img, M, (w, h), borderValue=(255, 255, 255))
    return out


def validate(pil_img: Image.Image, expected: str) -> dict:
    """Return {"pass", "score", "max": 3, "results": {cond: {"zx", "cv", "hits", "hit_count"}}, "thin"}.

    "zx" is the phone-like decode D (bool): pass needs it on full and small, score
    counts it on all three. "hits" lists the D combos that read the payload and
    "hit_count" is their number (0-9). "thin" flags a pass whose small condition
    hit on exactly one combo. "cv" is OpenCV on the unsoftened variant, advisory
    only, and never affects pass, score or thin.
    """
    img = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    results = {}
    for name, variant in _conditions(img).items():
        hits = _phone_hits(variant, expected)
        results[name] = {"zx": bool(hits), "cv": _decode_cv(variant) == expected,
                         "hits": hits, "hit_count": len(hits)}
    score = sum(r["zx"] for r in results.values())
    passed = all(results[c]["zx"] for c in GATES)
    return {"pass": passed, "score": score, "max": len(results), "results": results,
            "thin": passed and results["small"]["hit_count"] == 1}


def summary_line(v: dict) -> str:
    def mark(ok: bool) -> str:
        return "✓" if ok else "✗"

    flags = [f"{cond} zx{mark(r['zx'])} (cv{mark(r['cv'])})" for cond, r in v["results"].items()]
    return ("PASS " if v["pass"] else "FAIL ") + " | ".join(flags) + f"  ({v['score']}/{v['max']})"
