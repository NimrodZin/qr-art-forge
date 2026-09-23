---
title: QR Art Forge
emoji: 🌸
colorFrom: gray
colorTo: pink
sdk: gradio
sdk_version: 5.50.0
python_version: 3.11
app_file: app.py
pinned: false
license: mit
short_description: Aesthetic QR codes that actually scan
---

# QR Art Forge

Generates QR codes that read to a human as an image and to a phone camera as a link.

**Pipeline**
1. Level-H QR control image on a gray canvas (QR Code Monster v2 convention)
2. Batch generation with Stable Diffusion 1.5 + `monster-labs/control_v1p_sd15_qrcode_monster` (v2)
3. Every candidate is decoded by OpenCV **and** zxing-cpp under four conditions: full-res, phone-size downscale, perspective tilt, blur + contrast loss
4. Near-misses get an img2img rescue pass at higher ControlNet weight
5. Only images that pass everything are shown

**Deploy**: the Space mirrors the GitHub repo. Set `BASE_MODEL` in Space secrets to swap the SD1.5 checkpoint. See `docs/` for the contract.

Always test results on a real phone before publishing. Use short/dynamic links.
