# 05 — Open Discussion v0.2 (2026-10-17)

No standing. An entry closes only by becoming replacement text in 02–04; then it is marked closed, never deleted.

1. **Dynamic short links** — offer/require an editable redirect for printed use? Touches 02 payload, 04 M2.
2. **3D / anamorphic QR** — self-shadow, projection-mapped, Unreal-rendered codes (Nimrod's original interest). Out of v1–v3; possible M4. Touches 04.
3. **Animated QR** — AnimateQR / frame-safe animation. Same status as 2.
4. **Long payload policy** — 80 reject / 40 warn is a ruling; revisit with real users. Touches 02.
5. **Rate limiting and abuse** on the public Space — none in v1; needed before M3. Touches 04 M3, D4.
6. **Hide the QR vibe** — (1) bleed canvas 768×1024 with the code in the centre square; (2) finder-pattern softening via ControlNet mask, expected to cost pass rate. Touches 02 control image, 04 M2. Raised by Nimrod 2026-09-23.
7. **ZeroGPU duration** — Space requests 180 s per run though @GPU asks 120 s; investigate before M2 tuning (quota cost). Touches app.py.
8. **Reference image** — IP-Adapter style reference first (≈2.5 GB encoder, ~0.5 GB VRAM, +10–15 % time); img2img init second; both third. Needs P5 or batch 2 on the 4070. Nimrod 2026-09-26. Persistence settled: P6 (never stored), 2026-10-11.
9. **Negative prompt field** under Advanced, appended to the fixed default. Nimrod 2026-09-26.
10. **Reject archive and user negative** — the archive does not record the user's negative prompt (persisted-data schema; Nimrod's call). Raised by the m2-6 spec.
11. **UI screenshots on PRs** — 06 §4 approve-by-seeing via headless browser; deferred, text flag + `ui-change` label meanwhile (M2.8).
12. **Picture-first QR** — results read as a QR code first, a picture second (QR strength 1.35 sets the layout). Scanners read grey level at module centres only, so hue is free and module edges are free. Plan, judged by Nimrod's eye and phone: (1) baseline at QR strength 0.9 / 1.1 / 1.35; (2) centre-dot repair — lower strength, then correct luminance only in small dots at misread module centres, colour kept; (3) DiffQRCoder (WACV 2025, training-free, SD 1.5 + QR Monster v2, reports 99 % vs 60 % scan success; code public, licence not stated) as comparison. Winner becomes the M2 quality step (validation path: never-economize, 02 change). Ties to O1 and F1. Raised by Nimrod 2026-10-14. 2026-10-17: order A — F1 first, validator 02 v0.4 second, bleed canvas 02 v0.5 after; the F1 batch also tests a photoreal SD1.5 checkpoint via BASE_MODEL and a dappled-light prompt (Nimrod, planner chat).
13. **F1 phone-truth set** — protocol: 10 scans per device (iPhone, one Android), success = the payload opens within 3 s; strengths 0.9 / 1.1 / 1.35 × {DreamShaper 8, photoreal checkpoint} × {plain, dappled-light prompt}, 4 seeds per cell; feeds m2-10. Touches 02, 04 M2. Raised 2026-10-14 (m2-9 gate false positive).
