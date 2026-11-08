"""m2-18: default checkpoint Realistic Vision 5.1; BASE_MODEL still overrides it (03 D1 v0.10).

BASE is read at import, so each row executes a fresh copy of app.py under a private module
name. That leaves sys.modules["app"] and app._pipes alone (steps/m2-18/spec.md §2).
"""
import importlib.util
import itertools
import sys
from pathlib import Path

import diffusers
import pytest
import torch
from diffusers import DPMSolverMultistepScheduler

import app

APP_PY = Path(__file__).resolve().parent.parent / "app.py"
RV = "SG161222/Realistic_Vision_V5.1_noVAE"
DS8 = "Lykon/dreamshaper-8"
OTHER = "someone/other-sd15"
CN_REPO = "monster-labs/control_v1p_sd15_qrcode_monster"

_counter = itertools.count()


def fresh_app(monkeypatch, base_model):
    """Execute app.py once with BASE_MODEL set to base_model, or unset when it is None."""
    if base_model is None:
        monkeypatch.delenv("BASE_MODEL", raising=False)
    else:
        monkeypatch.setenv("BASE_MODEL", base_model)
    name = f"_qraf_m2_18_app_{next(_counter)}"
    spec = importlib.util.spec_from_file_location(name, APP_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def real_app_untouched():
    before_module = sys.modules["app"]
    before_pipes = app._pipes
    yield
    assert sys.modules["app"] is before_module
    assert app._pipes is before_pipes


class Rec:
    def __init__(self):
        self.pipe_calls = []  # (args, kwargs) per pipeline from_pretrained
        self.cn_calls = []    # (args, kwargs) per ControlNetModel from_pretrained


CN_OBJECT = object()  # what the fake ControlNetModel.from_pretrained returns


def load_with_fakes(monkeypatch, base_model) -> Rec:
    """Run _load_pipes() from a fresh app.py with fake diffusers classes; CPU only."""
    rec = Rec()

    class FakeCN:
        @classmethod
        def from_pretrained(cls, *a, **k):
            rec.cn_calls.append((a, k))
            return CN_OBJECT

    class FakeSched:
        config = {"cfg": 1}

    class FakePipe:
        def __init__(self):
            self.scheduler = FakeSched()
            self.components = {"vae": "V", "unet": "U", "scheduler": self.scheduler}

        @classmethod
        def from_pretrained(cls, *a, **k):
            rec.pipe_calls.append((a, k))
            return cls()

        def to(self, *a, **k):
            return self

        def enable_vae_slicing(self):
            pass

    class FakeI2I:
        def __init__(self, **k):
            pass

        def to(self, *a, **k):
            return self

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(diffusers, "ControlNetModel", FakeCN)
    monkeypatch.setattr(diffusers, "StableDiffusionControlNetPipeline", FakePipe)
    monkeypatch.setattr(diffusers, "StableDiffusionControlNetImg2ImgPipeline", FakeI2I)
    module = fresh_app(monkeypatch, base_model)
    monkeypatch.setattr(module, "make_scheduler", lambda config: FakeSched())
    out = module._load_pipes()
    assert set(out) == {"gen", "rescue"}
    return rec


# ---------------------------------------------------------------- rows 1–3: BASE at import
def test_base_defaults_to_realistic_vision_when_env_unset(monkeypatch):  # row 1
    assert fresh_app(monkeypatch, None).BASE == RV


def test_base_model_restores_dreamshaper(monkeypatch):  # row 2
    assert fresh_app(monkeypatch, DS8).BASE == DS8


def test_base_model_override_is_verbatim(monkeypatch):  # row 3
    assert fresh_app(monkeypatch, OTHER).BASE == OTHER


# ---------------------------------------------------------------- rows 4–6: _load_pipes with fakes
def test_default_load_uses_realistic_vision(monkeypatch):  # row 4
    rec = load_with_fakes(monkeypatch, None)
    assert len(rec.pipe_calls) == 1
    args, kwargs = rec.pipe_calls[0]
    assert args == (RV,)
    assert set(kwargs) == {"controlnet", "torch_dtype", "safety_checker"}
    assert kwargs["safety_checker"] is None
    assert kwargs["controlnet"] is CN_OBJECT


def test_dreamshaper_override_reaches_the_pipeline(monkeypatch):  # row 5
    rec = load_with_fakes(monkeypatch, DS8)
    assert len(rec.pipe_calls) == 1
    args, _ = rec.pipe_calls[0]
    assert args == (DS8,)


@pytest.mark.parametrize("base_model", [None, DS8], ids=["default", "dreamshaper"])
def test_controlnet_is_the_same_under_both_checkpoints(monkeypatch, base_model):  # row 6
    rec = load_with_fakes(monkeypatch, base_model)
    assert len(rec.cn_calls) == 1
    args, kwargs = rec.cn_calls[0]
    assert args == (CN_REPO,)
    assert kwargs["subfolder"] == "v2"


# ---------------------------------------------------------------- row 7: real config (network; tiny file)
def test_scheduler_builds_from_realistic_vision_config():  # row 7
    config = DPMSolverMultistepScheduler.load_config(RV, subfolder="scheduler")
    scheduler = app.make_scheduler(config)
    assert scheduler.config.algorithm_type == "dpmsolver++"
    assert scheduler.config.use_karras_sigmas is True
