# 02 — Core Spec v0.1 (2026-09-23)

Every change bumps the version and records what changed under "Changes".

## Payload
- Input is trimmed. A bare domain (contains ".", no spaces, no scheme) gets `https://` prepended. Any other text is encoded as-is.
- Hard limit 80 characters after normalisation → reject with a message. Warn above 40. (Ruling; see Open Discussion 4.)
- The payload is never altered beyond the above, and the exact encoded string is shown back to the user.

## Control image
- QR version auto-fit, error correction H, quiet zone 4 modules, black modules on white.
- Centred on a 768 × 768 mid-grey (RGB 128,128,128) canvas; module size = floor(768 / (modules + 8)); nearest-neighbour scaling.

## Validation — NEVER ECONOMIZE
- Decoders: OpenCV `cv2.QRCodeDetector` and zxing-cpp (`zxingcpp`).
- Conditions, applied to the exact candidate pixels:
  1. `full` — as generated.
  2. `small` — longest side resized to 480 px, INTER_AREA.
  3. `tilt` — perspective warp with destination corners TL (6 % w, 4 % h), TR (94 % w, 0), BR (w, h), BL (0, 97 % h), white border.
  4. `soft` — Gaussian blur σ = max(1, w/600), then contrast ×0.85, brightness +20.
- **Pass** ⇔ every decoder returns the exact payload string under every condition. Anything else is fail.
- Score = number of decoder×condition hits; used only for rescue eligibility (score ≥ max/2).

## Rescue
- At most one img2img pass per candidate: strength 0.35, ControlNet weight = min(2.0, weight + 0.5), same seed, steps = max(12, steps/2).
- The rescued image must pass the full validator; otherwise the candidate is dropped.

## Output
- Only passing images are returned to the gallery.
- The report lists every seed, its condition results, and whether rescue was applied and its result.
- The control image is shown.

## Invariant (hard constraint)
No image reaches the gallery without `validate(image, payload)["pass"] == True` on that exact pixel data.

## Changes
- v0.1 — initial.
