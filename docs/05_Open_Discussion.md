# 05 — Open Discussion

No standing. An entry closes only by becoming replacement text in 02–04; then it is marked closed, never deleted.

1. **Dynamic short links** — offer/require an editable redirect for printed use? Touches 02 payload, 04 M2.
2. **3D / anamorphic QR** — self-shadow, projection-mapped, Unreal-rendered codes (Nimrod's original interest). Out of v1–v3; possible M4. Touches 04.
3. **Animated QR** — AnimateQR / frame-safe animation. Same status as 2.
4. **Long payload policy** — 80 reject / 40 warn is a ruling; revisit with real users. Touches 02.
5. **Rate limiting and abuse** on the public Space — none in v1; needed before M3. Touches 04 M3, D4.
6. **Hide the QR vibe** — (1) bleed canvas 768×1024 with the code in the centre square; (2) finder-pattern softening via ControlNet mask, expected to cost pass rate. Touches 02 control image, 04 M2. Raised by Nimrod 2026-09-23.
7. **ZeroGPU duration** — Space requests 180 s per run though @GPU asks 120 s; investigate before M2 tuning (quota cost). Touches app.py.
8. **Reference image** — IP-Adapter style reference first (≈2.5 GB encoder, ~0.5 GB VRAM, +10–15 % time); img2img init second; both third. Needs P5 or batch 2 on the 4070. Nimrod 2026-09-26.
9. **Negative prompt field** under Advanced, appended to the fixed default. Nimrod 2026-09-26.
