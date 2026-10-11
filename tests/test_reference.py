"""m2-9: IP-Adapter style reference under Advanced (OD 8, P6). Rows refer to steps/m2-9/spec.md §2."""
import gc
import hashlib
import io
import json
import types
import weakref
from datetime import datetime, timezone

import diffusers
import pytest
import torch
from PIL import Image

import app
from qrbuild import make_qr

PAY = "nimrodzin.com"
GOOD = make_qr("https://" + PAY)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))
SETTINGS_KEYS = {"prompt", "batch", "weight", "steps", "cfg", "rescue", "seed"}
META_KEYS = {"run_id", "label", "payload", "settings", "pass", "score", "max", "results",
             "reference"}
REF_LABEL = "Style reference image (optional)"
STRENGTH_LABEL = "Reference strength"
DISCLOSURE = "Failed generations may be stored privately to improve quality."
GEN_KEYS = {"prompt", "negative_prompt", "image", "num_images_per_prompt",
            "controlnet_conditioning_scale", "num_inference_steps", "guidance_scale",
            "generator", "width", "height"}
RESCUE_KEYS = {"prompt", "negative_prompt", "image", "control_image", "strength",
               "controlnet_conditioning_scale", "num_inference_steps", "guidance_scale",
               "generator"}


def make_ref():
    return Image.new("RGB", (37, 23), (200, 10, 120))


@pytest.fixture(autouse=True)
def no_archive_env(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)


@pytest.fixture(autouse=True)
def keep_pipes_cache(monkeypatch):
    before = app._pipes
    yield
    assert app._pipes is before  # these tests never populate the cache
    monkeypatch.setattr(app, "_pipes", before)


def recording_pipes(gen_imgs, rescue_img=BAD):
    calls = {"gen": [], "rescue": []}

    def gen(*a, **k):
        calls["gen"].append((a, k))
        return list(gen_imgs)

    def rescue(*a, **k):
        calls["rescue"].append((a, k))
        return rescue_img
    return {"gen": gen, "rescue": rescue}, calls


def near_miss_validate(monkeypatch):
    real_validate = app.validate
    near = {"pass": False, "score": 1, "max": 3,
            "results": {c: {"zx": c == "full", "cv": False} for c in ("full", "small", "tilt")}}
    monkeypatch.setattr(app, "validate",
                        lambda im, p: near if im is BAD else real_validate(im, p))


def capture_archive(monkeypatch):
    seen = {}
    monkeypatch.setattr(app, "archive_rejects",
                        lambda r: (seen.setdefault("r", r), "x")[1])
    return seen


# ---------------------------------------------------------------- constants
def test_constants():
    assert app.IPA_REPO == "h94/IP-Adapter"
    assert app.IPA_SUBFOLDER == "models"
    assert app.IPA_WEIGHT == "ip-adapter_sd15.bin"
    assert app.REF_SCALE == 0.5


# ---------------------------------------------------------------- run_forge wiring (rows 1-6)
def test_no_reference_gen_kwargs_are_negative_only():  # row 1
    pipes, calls = recording_pipes([BAD])
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes)
    (_, k), = calls["gen"]
    assert set(k) == {"negative"}


def test_reference_forwarded_to_gen_with_default_scale():  # row 2
    r = make_ref()
    pipes0, calls0 = recording_pipes([BAD])
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes0)
    pipes, calls = recording_pipes([BAD])
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes, reference=r)
    (a0, _), = calls0["gen"]
    (a, k), = calls["gen"]
    assert set(k) == {"negative", "reference", "reference_scale"}
    assert k["reference"] is r
    assert k["reference_scale"] == 0.5 == app.REF_SCALE
    assert isinstance(k["reference_scale"], float)
    assert k["negative"] == app.NEG
    assert len(a) == len(a0)
    assert a[0] == a0[0] and a[2:] == a0[2:]
    assert [type(x) for x in a] == [type(x) for x in a0]
    assert a[1].size == a0[1].size and a[1].tobytes() == a0[1].tobytes()


@pytest.mark.parametrize("scale", [0.8, 1])
def test_reference_scale_forwarded_as_float(scale):  # row 3
    pipes, calls = recording_pipes([BAD])
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes,
                  reference=make_ref(), reference_scale=scale)
    (_, k), = calls["gen"]
    assert k["reference_scale"] == float(scale)
    assert isinstance(k["reference_scale"], float)


def test_rescue_gets_same_reference_as_gen(monkeypatch):  # row 4
    near_miss_validate(monkeypatch)
    r = make_ref()
    pipes, calls = recording_pipes([BAD], rescue_img=GOOD)
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, True, 1, pipes=pipes,
                  reference=r, reference_scale=0.7)
    assert len(calls["rescue"]) == 1
    (_, gk), = calls["gen"]
    (_, rk), = calls["rescue"]
    assert rk["reference"] is r
    assert rk["reference_scale"] == gk["reference_scale"] == 0.7


def test_rescue_without_reference_kwargs_are_negative_only(monkeypatch):  # row 5
    near_miss_validate(monkeypatch)
    pipes, calls = recording_pipes([BAD], rescue_img=GOOD)
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, True, 1, pipes=pipes)
    assert len(calls["rescue"]) == 1
    (_, rk), = calls["rescue"]
    assert set(rk) == {"negative"}


def test_gate_and_report_unchanged_with_reference():  # row 6
    pipes0, _ = recording_pipes([GOOD, BAD, BAD])
    _, report0, _ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1, pipes=pipes0)
    pipes, _ = recording_pipes([GOOD, BAD, BAD])
    surv, report, _ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1, pipes=pipes,
                                    reference=make_ref())
    assert len(surv) == 1 and surv[0][0] is GOOD
    assert "1/3 passed" in report
    assert report.splitlines()[-1] == "rejects not archived (HF_TOKEN/REJECTS_REPO unset)"
    assert report == report0


# ---------------------------------------------------------------- archive (rows 7-10)
def test_archive_meta_reference_true(monkeypatch):  # row 7
    seen = capture_archive(monkeypatch)
    pipes, _ = recording_pipes([GOOD, BAD, BAD])
    app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1, pipes=pipes, reference=make_ref())
    assert len(seen["r"]) == 2
    for _, _, meta in seen["r"]:
        assert meta["reference"] is True
        assert set(meta["settings"]) == SETTINGS_KEYS


def test_archive_meta_reference_false_without_reference(monkeypatch):  # row 8
    seen = capture_archive(monkeypatch)
    pipes, _ = recording_pipes([GOOD, BAD, BAD])
    app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1, pipes=pipes)
    assert len(seen["r"]) == 2
    for _, _, meta in seen["r"]:
        assert meta["reference"] is False


def test_archive_holds_nothing_derived_from_reference(monkeypatch):  # row 9
    seen = capture_archive(monkeypatch)
    r = make_ref()
    buf = io.BytesIO()
    r.save(buf, format="PNG")
    blobs = [r.tobytes(), buf.getvalue()]
    digests = {h(b).hexdigest() for b in blobs for h in (hashlib.md5, hashlib.sha1,
                                                         hashlib.sha256)}
    pipes, _ = recording_pipes([GOOD, BAD, BAD])
    app.run_forge(PAY, "p", 3, 1.35, 25, 7, False, 1, pipes=pipes, reference=r)
    assert len(seen["r"]) == 2
    for path, png, meta in seen["r"]:
        assert set(meta) == META_KEYS
        text = json.dumps(meta)
        for d in digests:
            assert d not in text
        for pair in ("[37, 23]", "37, 23", "37,23", "37x23", "(37, 23)"):
            assert pair not in text
        decoded = Image.open(io.BytesIO(png))
        assert decoded.size == BAD.size
        assert png != buf.getvalue()


NOW = datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)
SETTINGS = {"prompt": "p", "batch": 2, "weight": 1.35, "steps": 25, "cfg": 7.0,
            "rescue": True, "seed": 123}


def _entries():
    v = {"pass": False, "score": 0, "max": 3,
         "results": {c: {"zx": False, "cv": False} for c in ("full", "small", "tilt")}}
    return [("seed123", BAD, v)]


def test_build_reject_records_reference_defaults_false():  # row 10
    entries = _entries()
    (path, png, meta), = app.build_reject_records("https://" + PAY, SETTINGS, entries, now=NOW)
    assert meta["reference"] is False
    assert path == "runs/20260923T140509Z-123/seed123.png"
    assert Image.open(io.BytesIO(png)).size == BAD.size
    assert meta["payload"] == "https://" + PAY
    assert meta["settings"] == SETTINGS
    assert meta["results"] == entries[0][2]["results"]
    assert meta["label"] == "seed123"
    json.dumps(meta)


@pytest.mark.parametrize("flag, expected", [(True, True), (False, False), (1, True)])
def test_build_reject_records_reference_flag_is_bool(flag, expected):  # row 10 (keyword)
    (_, _, meta), = app.build_reject_records("https://" + PAY, SETTINGS, _entries(), now=NOW,
                                             reference=flag)
    assert meta["reference"] is expected


# ---------------------------------------------------------------- retention (row 11)
def test_run_forge_keeps_no_reference():  # row 11
    def gen(*a, **k):
        return [BAD]  # non-retaining: records nothing

    pipes = {"gen": gen, "rescue": lambda *a, **k: BAD}
    r = make_ref()
    wr = weakref.ref(r)
    app.run_forge(PAY, "p", 1, 1.35, 25, 7, False, 1, pipes=pipes, reference=r)
    del r
    gc.collect()
    assert wr() is None


# ---------------------------------------------------------------- forge (rows 12-13)
def _capture_run_forge(monkeypatch):
    seen = {}

    def fake(*a, **k):
        seen["a"], seen["k"] = a, k
        return [], "", None
    monkeypatch.setattr(app, "run_forge", fake)
    return seen


def test_forge_forwards_reference(monkeypatch):  # row 12
    seen = _capture_run_forge(monkeypatch)
    r = make_ref()
    app.forge(PAY, "p", 1, 1.35, 25, 7, False, 1, "n", r, 0.7)
    assert seen["k"]["negative"] == "n"
    assert seen["k"]["reference"] is r
    assert seen["k"]["reference_scale"] == 0.7


def test_forge_reference_defaults(monkeypatch):  # row 13
    seen = _capture_run_forge(monkeypatch)
    app.forge(PAY, "p", 1, 1.35, 25, 7, False, 1)
    assert "reference" in seen["k"] and seen["k"]["reference"] is None
    assert seen["k"]["reference_scale"] == app.REF_SCALE


# ---------------------------------------------------------------- _load_pipes with fakes (rows 14-22)
ENC = object()  # sentinel image encoder
FE = object()   # sentinel feature extractor


class Rec:
    def __init__(self):
        self.events = []          # ordered names: load, scale, unload, pipe, i2i
        self.load_calls = []
        self.scale_calls = []
        self.unload_calls = 0
        self.pipe_calls = []      # kwargs dicts (or key sets when non-retaining)
        self.i2i_calls = []
        self.pipe = None
        self.i2i = None


def install_fakes(monkeypatch, retain=True) -> Rec:
    rec = Rec()

    def record(kwargs):
        if retain:
            return dict(kwargs)
        return {k: (v is not None) for k, v in kwargs.items()}  # no objects kept

    class FakeCN:
        @classmethod
        def from_pretrained(cls, *a, **k):
            return "CN"

    class FakeSched:
        config = {"cfg": 1}

    class FakePipe:
        def __init__(self):
            self.scheduler = FakeSched()
            self.components = {"vae": "V", "unet": "U", "scheduler": self.scheduler}
            self.image_encoder = None
            self.feature_extractor = FE
            rec.pipe = self

        @classmethod
        def from_pretrained(cls, *a, **k):
            return cls()

        def to(self, *a, **k):
            return self

        def enable_vae_slicing(self):
            pass

        def load_ip_adapter(self, *a, **k):
            rec.events.append("load")
            rec.load_calls.append((a, k))
            self.image_encoder = ENC

        def set_ip_adapter_scale(self, *a, **k):
            rec.events.append("scale")
            rec.scale_calls.append((a, k))

        def unload_ip_adapter(self, *a, **k):
            rec.events.append("unload")
            rec.unload_calls += 1
            self.image_encoder = None

        def __call__(self, **k):
            rec.events.append("pipe")
            rec.pipe_calls.append(record(k))
            return types.SimpleNamespace(
                images=[Image.new("RGB", (8, 8)) for _ in range(k["num_images_per_prompt"])])

    class FakeI2I:
        def __init__(self, **k):
            self.image_encoder = None
            self.feature_extractor = FE
            rec.i2i = self

        def to(self, *a, **k):
            return self

        def enable_vae_slicing(self):
            pass

        def __call__(self, **k):
            rec.events.append("i2i")
            rec.i2i_calls.append(record(k))
            return types.SimpleNamespace(images=[Image.new("RGB", (8, 8))])

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(diffusers, "ControlNetModel", FakeCN)
    monkeypatch.setattr(diffusers, "StableDiffusionControlNetPipeline", FakePipe)
    monkeypatch.setattr(diffusers, "StableDiffusionControlNetImg2ImgPipeline", FakeI2I)
    monkeypatch.setattr(app, "make_scheduler", lambda config: FakeSched())
    return rec


C = make_qr("https://" + PAY)
I = Image.new("RGB", (768, 768), (50, 60, 70))


def _scale_value(call):
    a, k = call
    return a[0] if a else k["scale"]


def test_load_pipes_does_not_load_adapter(monkeypatch):  # row 14
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    assert set(out) == {"gen", "rescue"}
    assert rec.load_calls == []
    assert rec.events == []


def test_gen_without_reference_has_todays_kwargs(monkeypatch):  # row 15
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    out["gen"]("p", C, 2, 1.35, 25, 7, 1)
    (k,) = rec.pipe_calls
    assert set(k) == GEN_KEYS
    assert rec.events == ["pipe"]


def test_rescue_without_reference_has_todays_kwargs(monkeypatch):  # row 16
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    out["rescue"]("p", I, C, 1.35, 25, 7, 1)
    (k,) = rec.i2i_calls
    assert set(k) == RESCUE_KEYS
    assert rec.events == ["i2i"]


def _gen_with_ref(out, r, scale=0.6):
    return out["gen"]("p", C, 2, 1.35, 25, 7, 1, reference=r, reference_scale=scale)


def test_gen_with_reference_loads_adapter_and_passes_image(monkeypatch):  # row 17
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    r = make_ref()
    _gen_with_ref(out, r)
    assert rec.load_calls == [(("h94/IP-Adapter",),
                               {"subfolder": "models", "weight_name": "ip-adapter_sd15.bin"})]
    (sc,) = rec.scale_calls
    assert _scale_value(sc) == 0.6 and isinstance(_scale_value(sc), float)
    (k,) = rec.pipe_calls
    assert set(k) == GEN_KEYS | {"ip_adapter_image"}
    assert k["ip_adapter_image"] is r
    assert rec.events == ["load", "scale", "pipe"]


def test_rescue_with_reference_reuses_adapter(monkeypatch):  # row 18
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    r = make_ref()
    _gen_with_ref(out, r)
    out["rescue"]("p", I, C, 1.35, 25, 7, 1, reference=r, reference_scale=0.6)
    assert len(rec.load_calls) == 1
    assert len(rec.scale_calls) == 2 and _scale_value(rec.scale_calls[1]) == 0.6
    (k,) = rec.i2i_calls
    assert set(k) == RESCUE_KEYS | {"ip_adapter_image"}
    assert k["ip_adapter_image"] is r
    assert rec.i2i.image_encoder is ENC
    assert rec.i2i.feature_extractor is rec.pipe.feature_extractor
    assert rec.events[-2:] == ["scale", "i2i"]


def test_gen_without_reference_after_reference_unloads(monkeypatch):  # row 19
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    _gen_with_ref(out, make_ref())
    out["gen"]("p", C, 2, 1.35, 25, 7, 1)
    assert rec.unload_calls == 1
    assert rec.events == ["load", "scale", "pipe", "unload", "pipe"]
    assert set(rec.pipe_calls[-1]) == GEN_KEYS
    assert rec.i2i.image_encoder is None


def test_second_plain_gen_does_not_unload_again(monkeypatch):  # row 20
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    _gen_with_ref(out, make_ref())
    out["gen"]("p", C, 2, 1.35, 25, 7, 1)
    out["gen"]("p", C, 2, 1.35, 25, 7, 1)
    assert rec.unload_calls == 1
    assert len(rec.load_calls) == 1
    assert rec.events[-1] == "pipe" and rec.events.count("unload") == 1
    assert set(rec.pipe_calls[-1]) == GEN_KEYS


def test_adapter_loaded_once_across_reference_runs(monkeypatch):  # row 21
    rec = install_fakes(monkeypatch)
    out = app._load_pipes()
    _gen_with_ref(out, make_ref())
    _gen_with_ref(out, make_ref())
    assert len(rec.load_calls) == 1
    assert rec.unload_calls == 0


def test_closures_keep_no_reference(monkeypatch):  # row 22
    rec = install_fakes(monkeypatch, retain=False)
    out = app._load_pipes()
    r = make_ref()
    wr = weakref.ref(r)
    _gen_with_ref(out, r)
    assert rec.pipe_calls[-1].get("ip_adapter_image") is True
    del r
    gc.collect()
    assert wr() is None


# ---------------------------------------------------------------- UI (rows 23-26)
def _ancestors(block):
    node, out = block.parent, []
    while node is not None:
        out.append(node)
        node = node.parent
    return out


def _in_advanced(block):
    import gradio as gr
    return any(isinstance(n, gr.Accordion) and n.label == "Advanced" for n in _ancestors(block))


def test_ui_reference_image_and_strength_in_advanced():  # row 23
    import gradio as gr
    demo = app.build_ui()
    imgs = [b for b in demo.blocks.values() if isinstance(b, gr.Image) and b.label == REF_LABEL]
    sliders = [b for b in demo.blocks.values()
               if isinstance(b, gr.Slider) and b.label == STRENGTH_LABEL]
    assert len(imgs) == 1 and len(sliders) == 1
    (img,), (sl,) = imgs, sliders
    assert img.type == "pil"
    assert sl.value == 0.5 and sl.minimum == 0 and sl.maximum == 1 and sl.step == 0.05
    assert _in_advanced(img) and _in_advanced(sl)


def test_forge_click_has_eleven_inputs():  # row 24
    import gradio as gr
    demo = app.build_ui()
    (btn,) = [b for b in demo.blocks.values() if isinstance(b, gr.Button) and b.value == "Forge"]
    (dep,) = [f for f in demo.fns.values() if (btn._id, "click") in f.targets]
    ins = dep.inputs
    assert len(ins) == 11
    expected = [(gr.Textbox, "URL or text"), (gr.Textbox, "Image prompt"),
                (gr.Slider, "Batch size"),
                (gr.Slider, "QR strength (higher = scans easier, looks more like a code)"),
                (gr.Slider, "Steps"), (gr.Slider, "Guidance (CFG)"),
                (gr.Checkbox, "Rescue near-misses"), (gr.Number, "Seed (-1 = random)"),
                (gr.Textbox, "Negative prompt (added to the built-in list)"),
                (gr.Image, REF_LABEL), (gr.Slider, STRENGTH_LABEL)]
    assert [(type(c), c.label) for c in ins] == expected
    demo.get_api_info()


def test_blocks_delete_cache():  # row 25
    assert app.build_ui().delete_cache == (3600, 3600)


def test_disclosure_line_unchanged():  # row 26
    import gradio as gr
    demo = app.build_ui()
    values = [b.value for b in demo.blocks.values() if isinstance(b, gr.Markdown)]
    assert values.count(DISCLOSURE) == 1
