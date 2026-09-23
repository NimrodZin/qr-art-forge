"""Scan validation for aesthetic QR codes (docs/02 v0.2).

A candidate passes only if zxing-cpp decodes the exact payload under all three
softened conditions below. OpenCV is run and reported as advisory only.
"""
from __future__ import annotations
import numpy as np
import cv2
from PIL import Image

try:
    import zxingcpp
    HAVE_ZXING = True
except Exception:  # pragma: no cover
    HAVE_ZXING = False

_cv_det = cv2.QRCodeDetector()


def _decode_cv(img: np.ndarray) -> str:
    data, _, _ = _cv_det.detectAndDecode(img)
    return data or ""


def _decode_zx(img: np.ndarray) -> str:
    if not HAVE_ZXING:
        return ""
    res = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode)
    return res[0].text if res else ""


def _soften(img: np.ndarray) -> np.ndarray:
    """S(img): phone optics — blur, then contrast x0.85 and brightness +20."""
    w = img.shape[1]
    blur = cv2.GaussianBlur(img, (0, 0), sigmaX=max(1.0, w / 600))
    return cv2.convertScaleAbs(blur, alpha=0.85, beta=20)


def _conditions(img: np.ndarray) -> dict[str, np.ndarray]:
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

    # Every condition is seen through phone optics
    return {name: _soften(v) for name, v in out.items()}


def validate(pil_img: Image.Image, expected: str) -> dict:
    """Return {"pass", "score", "max": 3, "results": {cond: {"zx": bool, "cv": bool}}}.

    zxing gates; OpenCV is advisory and never affects pass or score.
    """
    img = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    results = {}
    for name, variant in _conditions(img).items():
        results[name] = {"zx": _decode_zx(variant) == expected,
                         "cv": _decode_cv(variant) == expected}
    score = sum(r["zx"] for r in results.values())
    return {"pass": score == len(results), "score": score, "max": len(results),
            "results": results}


def summary_line(v: dict) -> str:
    def mark(ok: bool) -> str:
        return "✓" if ok else "✗"

    flags = [f"{cond} zx{mark(r['zx'])} (cv{mark(r['cv'])})" for cond, r in v["results"].items()]
    return ("PASS " if v["pass"] else "FAIL ") + " | ".join(flags) + f"  ({v['score']}/{v['max']})"
