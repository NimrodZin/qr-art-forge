"""Payload normalisation and control-image construction. See docs/02_Core_Spec.md.

NEVER ECONOMIZE: changes here alter what gets encoded.
"""
from __future__ import annotations
import qrcode
from PIL import Image

SIZE = 768
GREY = (128, 128, 128)
HARD_LIMIT = 80
WARN_LIMIT = 40


class PayloadError(ValueError):
    pass


def normalize_payload(raw: str) -> tuple[str, str | None]:
    """Return (payload, warning). Raises PayloadError on reject."""
    p = (raw or "").strip()
    if not p:
        raise PayloadError("Enter a URL or text to encode.")
    low = p.lower()
    if (not low.startswith(("http://", "https://"))
            and "." in p and " " not in p):
        p = "https://" + p
    if len(p) > HARD_LIMIT:
        raise PayloadError(
            f"Payload is {len(p)} characters; limit is {HARD_LIMIT}. Use a short link.")
    warn = None
    if len(p) > WARN_LIMIT:
        warn = "Long payloads make dense codes that are hard to hide. A short link scans better."
    return p, warn


def make_qr(payload: str, size: int = SIZE) -> Image.Image:
    """Level-H QR, 4-module quiet zone, black on white, centred on a grey canvas."""
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, border=4, box_size=1)
    q.add_data(payload)
    q.make(fit=True)
    n = q.modules_count + 8
    module = size // n
    img = q.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((n * module, n * module), Image.NEAREST)
    canvas = Image.new("RGB", (size, size), GREY)
    off = (size - img.width) // 2
    canvas.paste(img, (off, off))
    return canvas
