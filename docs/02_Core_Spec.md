# 02 — Core Spec v0.3 (2026-09-24)

Every change bumps the version and records what changed under "Changes".

## Payload
- Input is trimmed. A bare domain (contains ".", no spaces, no scheme) gets `https://` prepended. Any other text is encoded as-is.
- Hard limit 80 characters after normalisation → reject with a message. Warn above 40. (Ruling; see Open Discussion 4.)
- The payload is never altered beyond the above, and the exact encoded string is shown back to the user.

## Control image
- QR version auto-fit, error correction H, quiet zone 4 modules, black modules on white.
- Centred on a 768 × 768 mid-grey (RGB 128,128,128) canvas; module size = floor(768 / (modules + 8)); nearest-neighbour scaling.

## Validation — NEVER ECONOMIZE (v0.3)
- Softening S_k(img): Gaussian blur σ_k = k · max(1, w/600) with w the variant's width, then contrast ×0.85, brightness +20; S_0 = contrast/brightness only, no blur.
- Phone-like decode D(img): zxing-cpp run with binarizers {LocalAverage, GlobalHistogram, FixedThreshold} on each of {img, S_1(img), S_2(img)}; D succeeds iff any of the nine returns the exact payload string.
- Conditions on the exact candidate pixels: `full` = img; `small` = resize longest side 480, INTER_AREA; `tilt` = perspective warp TL (6%w,4%h), TR (94%w,0), BR (w,h), BL (0,97%h), white border.
- Gating: **Pass** ⇔ D succeeds on all three conditions. Score = conditions where D succeeds (0–3); rescue eligibility: score ≥ 1.
- OpenCV `QRCodeDetector` on the unsoftened variant is reported as advisory only.

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
- v0.2 (2026-09-23) — zxing gates, OpenCV advisory; all conditions softened; three conditions. Provenance: run 1382759530, 4/4 rejects read on iPhone and Android while scoring ≤3/8 under v0.1; every one had zx-soft ✓ (Nimrod, this date).
- v0.2.1 (2026-09-23) — clarified σ basis. Provenance: M1.6 handover, Not certain 2.
- v0.3 (2026-09-24) — phone-like decode: 3 binarizers × 3 softening levels, any-hit. Provenance: run 55795690, 7/7 rejects read on phone, 7/7 pass v0.3 on all conditions, negatives fail (planner measurement, zxing-cpp 2.2.0).
- v0.3.1 (2026-09-26) — gallery serves PNG so displayed pixels are the validated pixels. Provenance: local/REPORT-local.md §5.
