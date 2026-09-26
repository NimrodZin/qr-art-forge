"""QR Art Forge — aesthetic QR codes that actually scan. See docs/ for the contract."""
from __future__ import annotations
import io
import json
import os
import random
from datetime import datetime, timezone
from typing import Callable

import gradio as gr
from PIL import Image

from qrbuild import normalize_payload, make_qr, PayloadError, SIZE
from validator import validate, summary_line

BASE = os.environ.get("BASE_MODEL", "Lykon/dreamshaper-8")
CN = "monster-labs/control_v1p_sd15_qrcode_monster"
NEG = ("ugly, disfigured, low quality, blurry, nsfw, text, watermark, "
       "flat, grid, checkerboard, monochrome squares")

try:
    import spaces
    GPU = spaces.GPU
except Exception:  # local / CI
    def GPU(f=None, **_):
        return f if f else (lambda g: g)


# ---------------------------------------------------------------- pipelines (lazy)
_pipes: dict | None = None


def make_scheduler(config: dict):
    from diffusers import DPMSolverMultistepScheduler
    return DPMSolverMultistepScheduler.from_config(
        config, use_karras_sigmas=True, algorithm_type="dpmsolver++")


def _load_pipes() -> dict:
    import torch
    from diffusers import (ControlNetModel, StableDiffusionControlNetPipeline,
                           StableDiffusionControlNetImg2ImgPipeline)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    cn = ControlNetModel.from_pretrained(CN, subfolder="v2", torch_dtype=dtype)
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        BASE, controlnet=cn, torch_dtype=dtype, safety_checker=None)
    pipe.scheduler = make_scheduler(pipe.scheduler.config)
    i2i = StableDiffusionControlNetImg2ImgPipeline(**pipe.components)
    pipe.to(device)
    i2i.to(device)

    def gen(prompt, control, n, weight, steps, cfg, seed):
        gens = [torch.Generator(device).manual_seed(seed + i) for i in range(n)]
        return pipe(prompt=prompt, negative_prompt=NEG, image=control,
                    num_images_per_prompt=n, controlnet_conditioning_scale=weight,
                    num_inference_steps=steps, guidance_scale=cfg, generator=gens,
                    width=SIZE, height=SIZE).images

    def rescue(prompt, image, control, weight, steps, cfg, seed):
        return i2i(prompt=prompt, negative_prompt=NEG, image=image, control_image=control,
                   strength=0.35, controlnet_conditioning_scale=min(2.0, weight + 0.5),
                   num_inference_steps=max(12, steps // 2), guidance_scale=cfg,
                   generator=torch.Generator(device).manual_seed(seed)).images[0]

    return {"gen": gen, "rescue": rescue}


def get_pipes() -> dict:
    """Tests monkeypatch this to inject fakes."""
    global _pipes
    if _pipes is None:
        _pipes = _load_pipes()
    return _pipes


# ---------------------------------------------------------------- reject archive (owner-only diagnostics)
def build_reject_records(payload: str, settings: dict,
                         entries: list[tuple[str, Image.Image, dict]],
                         now: datetime | None = None) -> list[tuple[str, bytes, dict]]:
    """Pure: (label, image, validate-result) → (runs/<run_id>/<label>.png, png_bytes, meta)."""
    now = now or datetime.now(timezone.utc)
    run_id = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{settings['seed']}"
    records = []
    for label, im, v in entries:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        meta = {"run_id": run_id, "label": label, "payload": payload, "settings": settings,
                "pass": v["pass"], "score": v["score"], "max": v["max"], "results": v["results"]}
        records.append((f"runs/{run_id}/{label}.png", buf.getvalue(), meta))
    return records


def archive_rejects(records: list[tuple[str, bytes, dict]]) -> str:
    """Upload to the owner's private dataset if HF_TOKEN and REJECTS_REPO are set. Never raises."""
    if not records:
        return "no rejects to archive"
    token, repo = os.environ.get("HF_TOKEN"), os.environ.get("REJECTS_REPO")
    if not (token and repo):
        return "rejects not archived (HF_TOKEN/REJECTS_REPO unset)"
    try:
        import huggingface_hub as hf
        api = hf.HfApi(token=token)
        api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
        ops = []
        for path, png, meta in records:
            ops.append(hf.CommitOperationAdd(path_in_repo=path, path_or_fileobj=png))
            ops.append(hf.CommitOperationAdd(
                path_in_repo=path[:-len(".png")] + ".json",
                path_or_fileobj=json.dumps(meta, indent=2).encode()))
        info = api.create_commit(repo, operations=ops, repo_type="dataset",
                                 commit_message=f"rejects {records[0][2]['run_id']}")
        return str(info.commit_url)
    except Exception as e:  # message may carry request details; report the type only
        return f"archive failed: {type(e).__name__}"


# ---------------------------------------------------------------- core loop
def run_forge(payload_raw: str, prompt: str, batch: int, weight: float, steps: int,
              cfg: float, rescue: bool, seed: int, pipes: dict | None = None,
              progress: Callable | None = None):
    """Pure function: returns (survivors, report, control). Gate rule lives here."""
    pipes = pipes or get_pipes()
    payload, warn = normalize_payload(payload_raw)
    control = make_qr(payload)
    seed = int(seed) if seed >= 0 else random.randint(0, 2**31 - 1)
    if progress:
        progress(0.05, desc="Generating batch")
    imgs = pipes["gen"](prompt, control, int(batch), float(weight), int(steps), float(cfg), seed)

    survivors, report, rejects = [], [], []
    for i, im in enumerate(imgs):
        if progress:
            progress(0.5 + 0.4 * i / max(1, len(imgs)), desc=f"Testing {i+1}/{len(imgs)}")
        v = validate(im, payload)
        tag = f"seed {seed+i}: " + summary_line(v)
        if not v["pass"]:
            rejects.append((f"seed{seed+i}", im, v))
        if not v["pass"] and rescue and v["score"] >= 1:
            im2 = pipes["rescue"](prompt, im, control, float(weight), int(steps), float(cfg), seed + i)
            v2 = validate(im2, payload)
            tag += " → rescue " + summary_line(v2)
            if v2["pass"]:
                im, v = im2, v2
            else:
                rejects.append((f"seed{seed+i}-rescue", im2, v2))
        report.append(tag)
        if v["pass"]:  # THE GATE — the only way into the gallery
            survivors.append((im, f"seed {seed+i}"))

    header = f"{len(survivors)}/{len(imgs)} passed. Encoded: {payload}\n"
    if warn:
        header += warn + "\n"
    header += "Always test on a real phone before publishing.\n\n"
    settings = {"prompt": prompt, "batch": int(batch), "weight": float(weight),
                "steps": int(steps), "cfg": float(cfg), "rescue": bool(rescue), "seed": seed}
    report.append(archive_rejects(build_reject_records(payload, settings, rejects)))
    return survivors, header + "\n".join(report), control


@GPU(duration=120)
def forge(payload, prompt, batch, weight, steps, cfg, rescue, seed, progress=gr.Progress()):
    try:
        return run_forge(payload, prompt, batch, weight, steps, cfg, rescue, seed, progress=progress)
    except PayloadError as e:
        raise gr.Error(str(e))


# ---------------------------------------------------------------- UI
def build_ui() -> gr.Blocks:
    with gr.Blocks(title="QR Art Forge") as demo:
        gr.Markdown("# QR Art Forge\n"
                    "Aesthetic QR codes a human sees as a picture and a phone reads as a link. "
                    "Every result shown has been read by a phone-grade decoder under three scan conditions.")
        with gr.Row():
            with gr.Column(scale=1):
                payload = gr.Textbox(label="URL or text", placeholder="example.com")
                prompt = gr.Textbox(label="Image prompt", lines=3,
                                    placeholder="a peony in full bloom, botanical illustration, dark background")
                with gr.Accordion("Advanced", open=False):
                    batch = gr.Slider(1, 8, value=4, step=1, label="Batch size")
                    weight = gr.Slider(0.8, 2.0, value=1.35, step=0.05,
                                       label="QR strength (higher = scans easier, looks more like a code)")
                    steps = gr.Slider(15, 40, value=25, step=1, label="Steps")
                    cfg = gr.Slider(4, 12, value=7, step=0.5, label="Guidance (CFG)")
                    rescue = gr.Checkbox(value=True, label="Rescue near-misses")
                    seed = gr.Number(value=-1, label="Seed (-1 = random)", precision=0)
                go = gr.Button("Forge", variant="primary")
                gr.Markdown("Failed generations may be stored privately to improve quality.")
            with gr.Column(scale=2):
                gallery = gr.Gallery(label="Scannable results", columns=2, height=560, format="png")
                report = gr.Textbox(label="Scan report", lines=8)
                ctrl = gr.Image(label="Control image used", height=200)
        go.click(forge, [payload, prompt, batch, weight, steps, cfg, rescue, seed],
                 [gallery, report, ctrl])
        gr.Markdown("**Tips** — keep payloads short; subjects with strong light/dark structure hide the "
                    "code best; if nothing passes, raise QR strength by 0.2 and retry.")
    return demo


if __name__ == "__main__":
    build_ui().queue().launch()
