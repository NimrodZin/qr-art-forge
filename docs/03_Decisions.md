# 03 — Decisions v0.3 (2026-09-26)

Statuses: Decided (settled; not re-argued unless Nimrod raises it or new evidence) · Provisional (built on; flagged when a task exposes a reason to revisit) · Open (never silently resolved; a dependent task names it and takes the smallest hedge) · Superseded (kept, with pointer).

## Decided
- D1 Base pipeline v1: SD1.5 + QR Code Monster v2 ControlNet (`monster-labs/control_v1p_sd15_qrcode_monster`, subfolder v2); DreamShaper 8 checkpoint, swappable via `BASE_MODEL`.
- D2 Hosting v1: Hugging Face Space, ZeroGPU, mirrored from GitHub. Note 2026-09-26: the Space stays up but is not promoted; development and the loop run on the Windows PC; public production is decided at M3 (see O2).
- D3 Validation contract as in 02 v0.3: phone-like decode (3 binarizers × 3 softening levels, any-hit) gates; OpenCV advisory; three conditions. (Superseded: v0.1 two decoders/four conditions; v0.2 zxing single-binarizer.)
- D4 No accounts, no persistence, no payment in v1.
- D5 Workflow: Autonomous Build Loop; local orchestrator on Nimrod's Mac via `claude -p`; GitHub PRs + Actions.
- D6 Gradio 5.x replaces Gradio 4.x in the stack (PR #4).

## Provisional
- P1 Rescue policy: single img2img pass at strength 0.35.
- P2 Default QR strength (ControlNet conditioning scale) 1.35.
- P3 768 px output.
- P4 Owner-only reject archive to a private HF dataset (M1.5); disclosure line in UI. Nimrod: keep (chat 2026-09-23).
- P5 VAE slicing on CUDA (≤ 2/255 pixel change; validator runs on final pixels). Off by default until the loop measures pass rate with it on. Provenance: local/REPORT-local.md §4.

## Open
- O1 Repair method for v2: DiffQRCoder-style gradient repair vs img2img rescue. Blocks nothing in v1; affects M2 spec.
- O2 Public backend at M3: serverless GPU (Modal, RunPod, fal) vs AWS vs self-hosted PC behind a tunnel. Nimrod 2026-09-26: 'when I go public we deal with the limitations'. Blocks M3.
- O3 Public-site UX: one-button vs designer knobs. Product decision; needed before M3.

## Changes
- v0.1 — initial.
- v0.2 (2026-09-23) — D3 updated, D6, P4 added.
- v0.3 (2026-09-26) — D3 → 02 v0.3; D2 note; P5; O2 options.
