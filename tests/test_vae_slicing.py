"""P5 decided: VAE slicing on CUDA by default; QRAF_VAE_SLICING=0 disables (steps/m2-7b/spec.md §2)."""
import os

import diffusers
import pytest
import torch
from PIL import Image

import app
from qrbuild import make_qr

PAY = "nimrodzin.com"
GOOD = make_qr("https://" + PAY)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))
VAR = "QRAF_VAE_SLICING"


# ---------------------------------------------------------------- rows 1–9: the pure helper
def test_cuda_default_is_true():  # row 1
    assert app.vae_slicing_enabled("cuda", {}) is True


def test_cuda_flag_one_is_true():  # row 2
    assert app.vae_slicing_enabled("cuda", {VAR: "1"}) is True


def test_cuda_flag_zero_is_false():  # row 3
    assert app.vae_slicing_enabled("cuda", {VAR: "0"}) is False


@pytest.mark.parametrize("e", [{}, {VAR: "1"}, {VAR: "0"}])
def test_cpu_is_always_false(e):  # row 4
    assert app.vae_slicing_enabled("cpu", e) is False


@pytest.mark.parametrize("v", ["", "true", "false", "off", "no", " 0", "0 ", "00", "2"])
def test_only_exact_zero_disables(v):  # row 5
    assert app.vae_slicing_enabled("cuda", {VAR: v}) is True


def test_env_unset_is_true(monkeypatch):  # row 6
    monkeypatch.delenv(VAR, raising=False)
    assert app.vae_slicing_enabled("cuda") is True


def test_env_read_at_call_time(monkeypatch):  # row 7
    monkeypatch.setenv(VAR, "0")
    assert app.vae_slicing_enabled("cuda") is False


def test_env_set_on_cpu_is_false(monkeypatch):  # row 8
    monkeypatch.setenv(VAR, "1")
    assert app.vae_slicing_enabled("cpu") is False


def test_helper_is_stable_and_leaves_environ_alone():  # row 9
    before = dict(os.environ)
    a = app.vae_slicing_enabled("cuda", {})
    b = app.vae_slicing_enabled("cuda", {})
    assert a is b is True
    assert dict(os.environ) == before


# ---------------------------------------------------------------- rows 10–15: _load_pipes with fakes
VAE = object()  # sentinel shared VAE


class Rec:
    def __init__(self):
        self.calls = []        # every call any fake sees, in order
        self.slicing = 0       # txt2img enable_vae_slicing count
        self.i2i_slicing = 0   # img2img enable_vae_slicing count
        self.i2i_kwargs = None


def install_fakes(monkeypatch, cuda: bool) -> Rec:
    rec = Rec()

    class FakeCN:
        @classmethod
        def from_pretrained(cls, *a, **k):
            rec.calls.append(("cn.from_pretrained", a, tuple(sorted(k))))
            return "CN"

    class FakeSched:
        config = {"cfg": 1}

    class FakePipe:
        def __init__(self):
            self.scheduler = FakeSched()
            self.components = {"vae": VAE, "unet": "U", "scheduler": self.scheduler}

        @classmethod
        def from_pretrained(cls, *a, **k):
            rec.calls.append(("pipe.from_pretrained", a,
                              tuple(sorted((key, k[key] if key != "torch_dtype" else str(k[key]))
                                           for key in k))))
            return cls()

        def to(self, *a, **k):
            rec.calls.append(("pipe.to", a, tuple(sorted(k.items()))))
            return self

        def enable_vae_slicing(self):
            rec.slicing += 1

    class FakeI2I:
        def __init__(self, **k):
            rec.i2i_kwargs = k
            rec.calls.append(("i2i.__init__", (), tuple(sorted(k))))

        def to(self, *a, **k):
            rec.calls.append(("i2i.to", a, tuple(sorted(k.items()))))
            return self

        def enable_vae_slicing(self):
            rec.i2i_slicing += 1

    monkeypatch.setattr(torch.cuda, "is_available", lambda: cuda)
    monkeypatch.setattr(diffusers, "ControlNetModel", FakeCN)
    monkeypatch.setattr(diffusers, "StableDiffusionControlNetPipeline", FakePipe)
    monkeypatch.setattr(diffusers, "StableDiffusionControlNetImg2ImgPipeline", FakeI2I)
    monkeypatch.setattr(app, "make_scheduler", lambda config: FakeSched())
    return rec


@pytest.fixture(autouse=True)
def keep_pipes_cache(monkeypatch):
    before = app._pipes
    yield
    assert app._pipes is before  # these tests never populate the cache
    monkeypatch.setattr(app, "_pipes", before)


def test_default_on_cuda_enables_slicing_once(monkeypatch):  # row 10
    rec = install_fakes(monkeypatch, cuda=True)
    monkeypatch.delenv(VAR, raising=False)
    out = app._load_pipes()
    assert rec.slicing == 1
    assert isinstance(out, dict) and set(out) == {"gen", "rescue"}


def test_flag_one_enables_slicing_once(monkeypatch):  # row 11
    rec = install_fakes(monkeypatch, cuda=True)
    monkeypatch.setenv(VAR, "1")
    app._load_pipes()
    assert rec.slicing == 1


def test_flag_zero_does_not_enable(monkeypatch):  # row 12
    rec = install_fakes(monkeypatch, cuda=True)
    monkeypatch.setenv(VAR, "0")
    app._load_pipes()
    assert rec.slicing == 0


def test_no_cuda_does_not_enable(monkeypatch):  # row 13
    rec = install_fakes(monkeypatch, cuda=False)
    monkeypatch.delenv(VAR, raising=False)
    app._load_pipes()
    assert rec.slicing == 0


def test_rescue_shares_the_sliced_vae(monkeypatch):  # row 14
    rec = install_fakes(monkeypatch, cuda=True)
    monkeypatch.delenv(VAR, raising=False)
    app._load_pipes()
    assert rec.slicing == 1
    assert rec.i2i_kwargs is not None and rec.i2i_kwargs["vae"] is VAE
    assert rec.i2i_slicing == 0


def test_flag_changes_nothing_else_in_load(monkeypatch):  # row 15
    rec_on = install_fakes(monkeypatch, cuda=True)
    monkeypatch.delenv(VAR, raising=False)
    app._load_pipes()
    rec_off = install_fakes(monkeypatch, cuda=True)
    monkeypatch.setenv(VAR, "0")
    app._load_pipes()
    assert rec_on.slicing == 1 and rec_off.slicing == 0
    assert rec_on.calls == rec_off.calls
    for rec in (rec_on, rec_off):
        (pf,) = [c for c in rec.calls if c[0] == "pipe.from_pretrained"]
        assert pf[1] == (app.BASE,)
        kw = dict(pf[2])
        assert set(kw) == {"controlnet", "torch_dtype", "safety_checker"}
        assert kw["controlnet"] == "CN" and kw["safety_checker"] is None
        assert ("pipe.to", ("cuda",), ()) in rec.calls
        assert ("i2i.to", ("cuda",), ()) in rec.calls


# ---------------------------------------------------------------- row 16: no effect outside _load_pipes
def test_flag_has_no_effect_on_run_forge(monkeypatch):  # row 16
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)
    pipes = {"gen": lambda *a, **k: [GOOD, BAD, BAD], "rescue": lambda *a, **k: BAD}
    monkeypatch.setenv(VAR, "0")
    surv_off, rep_off, _ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, True, 1, pipes=pipes)
    monkeypatch.delenv(VAR)
    surv_on, rep_on, _ = app.run_forge(PAY, "p", 3, 1.35, 25, 7, True, 1, pipes=pipes)
    assert rep_on == rep_off
    assert "1/3 passed" in rep_on
    assert rep_on.splitlines()[-1] == "rejects not archived (HF_TOKEN/REJECTS_REPO unset)"
    assert [(id(im), lbl) for im, lbl in surv_on] == [(id(im), lbl) for im, lbl in surv_off]
    assert len(surv_on) == 1 and surv_on[0][0] is GOOD
