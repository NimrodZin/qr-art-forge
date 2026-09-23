"""Scan validation for aesthetic QR codes.

A candidate passes only if it decodes to the expected payload under all
conditions below, using two independent decoders (OpenCV and zxing-cpp).
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

    # Slight blur + contrast loss (cheap screen / print)
    blur = cv2.GaussianBlur(img, (0, 0), sigmaX=max(1.0, w / 600))
    out["soft"] = cv2.convertScaleAbs(blur, alpha=0.85, beta=20)
    return out


def validate(pil_img: Image.Image, expected: str) -> dict:
    """Return {"pass": bool, "score": int, "results": {cond: {"cv": bool, "zx": bool}}}."""
    img = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
    results = {}
    hits = 0
    total = 0
    for name, variant in _conditions(img).items():
        cv_ok = _decode_cv(variant) == expected
        zx_ok = _decode_zx(variant) == expected if HAVE_ZXING else None
        results[name] = {"cv": cv_ok, "zx": zx_ok}
        for ok in (cv_ok, zx_ok):
            if ok is None:
                continue
            total += 1
            hits += int(ok)
    # Pass = every decoder agrees on every condition
    passed = all(v["cv"] and (v["zx"] is None or v["zx"]) for v in results.values())
    return {"pass": passed, "score": hits, "max": total, "results": results}


def summary_line(v: dict) -> str:
    flags = []
    for cond, r in v["results"].items():
        mark = "✓" if r["cv"] and (r["zx"] is None or r["zx"]) else "✗"
        flags.append(f"{cond}{mark}")
    return ("PASS " if v["pass"] else "FAIL ") + " ".join(flags) + f"  ({v['score']}/{v['max']})"
