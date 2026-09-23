# 01 — Brief v1.0 (2026-09-23)

## Who it is for
- v1: Nimrod and fellow designers/producers who need a scannable poster or programme code that looks like art.
- v2: the general public via Nimrod's own site.
Ruling: one primary path (URL + prompt + Forge) with all knobs behind "Advanced", so one build serves both.

## What ships first (v1)
A public Hugging Face Space where a user enters a URL and a prompt and receives only scannable results, 768 px, with a scan report. No accounts, no payment, no history. Everything else (upscaling, presets, batch export, own-domain site) is v2.

## Success criteria (v1)
1. Gate: Nimrod scans 3 of 3 outputs on iPhone and Android at arm's length and lands on the exact payload.
2. Pass rate: ≥ 50 % of a default batch (4 images, default settings, short URL) survives validation without rescue; ≥ 75 % with rescue.
3. Look: among survivors, at least one Nimrod would put on a poster — his call, recorded in the gate note.
4. Time: a 4-image batch returns in under 3 minutes on ZeroGPU.
5. Nothing unscannable is ever displayed (hard constraint, tested).
