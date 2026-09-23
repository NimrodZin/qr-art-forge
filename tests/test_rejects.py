"""Owner-only reject archive: pure record building + opt-in upload (network always mocked)."""
import io
import json
from datetime import datetime, timezone

import pytest
from PIL import Image

import app
from qrbuild import make_qr

PAY = "https://nimrodzin.com"
SETTINGS = {"prompt": "p", "batch": 2, "weight": 1.35, "steps": 25, "cfg": 7.0,
            "rescue": True, "seed": 123}
BAD = Image.new("RGB", (768, 768), (90, 90, 90))
NOW = datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)


def _entries():
    v = {"pass": False, "score": 0, "max": 8,
         "results": {c: {"cv": False, "zx": False} for c in ("full", "small", "tilt", "soft")}}
    small = Image.new("RGB", (512, 384), (10, 20, 30))
    return [("seed123", BAD, v), ("seed123-rescue", small, v)]


# (a) build_reject_records is pure
def test_build_reject_records_paths_and_contents():
    entries = _entries()
    recs = app.build_reject_records(PAY, SETTINGS, entries, now=NOW)
    assert [r[0] for r in recs] == ["runs/20260923T140509Z-123/seed123.png",
                                   "runs/20260923T140509Z-123/seed123-rescue.png"]
    for (path, png, meta), (label, im, v) in zip(recs, entries):
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert Image.open(io.BytesIO(png)).size == im.size
        assert meta["payload"] == PAY
        assert meta["settings"] == SETTINGS
        assert meta["results"] == v["results"]
        assert meta["label"] == label
        json.dumps(meta)  # serialisable


def test_build_reject_records_is_deterministic():
    a = app.build_reject_records(PAY, SETTINGS, _entries(), now=NOW)
    b = app.build_reject_records(PAY, SETTINGS, _entries(), now=NOW)
    assert a == b


def test_build_reject_records_defaults_to_utc_now():
    recs = app.build_reject_records(PAY, SETTINGS, _entries()[:1])
    run_id = recs[0][0].split("/")[1]
    stamp, seed = run_id.split("-")
    datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
    assert seed == "123"


# (b) env unset → no network
def test_archive_unset_env_makes_no_call(monkeypatch):
    import huggingface_hub

    def boom(*a, **k):
        raise AssertionError("network touched")
    monkeypatch.setattr(huggingface_hub, "HfApi", boom)
    recs = app.build_reject_records(PAY, SETTINGS, _entries(), now=NOW)
    assert app.archive_rejects(recs) == "rejects not archived (HF_TOKEN/REJECTS_REPO unset)"


def test_archive_needs_both_env_vars(monkeypatch):
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "HfApi", lambda *a, **k: 1 / 0)
    monkeypatch.setenv("HF_TOKEN", "hf_secret")
    recs = app.build_reject_records(PAY, SETTINGS, _entries(), now=NOW)
    assert "unset" in app.archive_rejects(recs)


# (c) env set → one create_commit with all files
class FakeApi:
    instances = []

    def __init__(self, token=None, **_):
        self.token = token
        self.repos, self.commits = [], []
        FakeApi.instances.append(self)

    def create_repo(self, repo_id, **kw):
        self.repos.append((repo_id, kw))

    def create_commit(self, repo_id, operations, **kw):
        self.commits.append((repo_id, list(operations), kw))

        class Info:
            commit_url = "https://huggingface.co/datasets/o/r/commit/abc"
        return Info()


@pytest.fixture
def fake_hf(monkeypatch):
    import huggingface_hub
    FakeApi.instances = []
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setenv("HF_TOKEN", "hf_secret")
    monkeypatch.setenv("REJECTS_REPO", "o/r")
    return FakeApi


def test_archive_one_commit_with_png_and_json_per_record(fake_hf):
    recs = app.build_reject_records(PAY, SETTINGS, _entries(), now=NOW)
    out = app.archive_rejects(recs)
    assert out == "https://huggingface.co/datasets/o/r/commit/abc"
    (api,) = fake_hf.instances
    assert api.token == "hf_secret"
    assert api.repos == [("o/r", {"repo_type": "dataset", "private": True, "exist_ok": True})]
    assert len(api.commits) == 1
    repo, ops, kw = api.commits[0]
    assert repo == "o/r" and kw.get("repo_type") == "dataset"
    assert len(ops) == 2 * len(recs)
    paths = sorted(op.path_in_repo for op in ops)
    assert paths == sorted([p for p, *_ in recs] + [p[:-4] + ".json" for p, *_ in recs])


def test_archive_exception_is_swallowed_without_token(fake_hf, monkeypatch):
    def fail(self, *a, **k):
        raise RuntimeError("401 for token hf_secret")
    monkeypatch.setattr(FakeApi, "create_commit", fail)
    recs = app.build_reject_records(PAY, SETTINGS, _entries(), now=NOW)
    out = app.archive_rejects(recs)
    assert out == "archive failed: RuntimeError"
    assert "hf_secret" not in out


def test_archive_nothing_to_do(fake_hf):
    assert app.archive_rejects([]) == "no rejects to archive"
    assert fake_hf.instances == []


# run_forge wiring
def _pipes(gen, rescue_img):
    return {"gen": lambda *a, **k: gen, "rescue": lambda *a, **k: rescue_img}


def test_run_forge_archives_rejects_not_survivors(monkeypatch):
    good = make_qr(PAY)
    seen = {}

    def fake_archive(records):
        seen["records"] = records
        return "ARCHIVE-LINE"
    monkeypatch.setattr(app, "archive_rejects", fake_archive)
    surv, report, _ = app.run_forge("nimrodzin.com", "p", 2, 1.35, 25, 7, False, 5,
                                    pipes=_pipes([good, BAD], BAD))
    assert len(surv) == 1
    assert report.splitlines()[-1] == "ARCHIVE-LINE"
    labels = [p.rsplit("/", 1)[1] for p, *_ in seen["records"]]
    assert labels == ["seed6.png"]
    _, _, meta = seen["records"][0]
    assert meta["payload"] == PAY and meta["settings"]["seed"] == 5


def test_run_forge_archives_failed_rescue_attempts(monkeypatch):
    seen = {}
    monkeypatch.setattr(app, "archive_rejects",
                        lambda r: (seen.setdefault("r", r), "x")[1])
    # force rescue eligibility: make validate report a near-miss for the original
    real_validate = app.validate
    near = {"pass": False, "score": 6, "max": 8,
            "results": {c: {"cv": True, "zx": c != "soft"} for c in ("full", "small", "tilt", "soft")}}
    monkeypatch.setattr(app, "validate",
                        lambda im, p: near if im is BAD else real_validate(im, p))
    rescued = Image.new("RGB", (768, 768), (100, 100, 100))
    surv, report, _ = app.run_forge("nimrodzin.com", "p", 1, 1.35, 25, 7, True, 9,
                                    pipes=_pipes([BAD], rescued))
    assert surv == []
    labels = [p.rsplit("/", 1)[1] for p, *_ in seen["r"]]
    assert labels == ["seed9.png", "seed9-rescue.png"]


def test_run_forge_never_archives_a_passing_rescue(monkeypatch):
    seen = {}
    monkeypatch.setattr(app, "archive_rejects",
                        lambda r: (seen.setdefault("r", r), "x")[1])
    good = make_qr(PAY)
    real_validate = app.validate
    near = {"pass": False, "score": 6, "max": 8,
            "results": {c: {"cv": True, "zx": c != "soft"} for c in ("full", "small", "tilt", "soft")}}
    monkeypatch.setattr(app, "validate",
                        lambda im, p: near if im is BAD else real_validate(im, p))
    surv, _, _ = app.run_forge("nimrodzin.com", "p", 1, 1.35, 25, 7, True, 9,
                               pipes=_pipes([BAD], good))
    assert len(surv) == 1 and surv[0][0] is good
    labels = [p.rsplit("/", 1)[1] for p, *_ in seen["r"]]
    assert labels == ["seed9.png"]
    assert all(im_bytes != _png(good) for _, im_bytes, _ in seen["r"])


def _png(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_ui_discloses_reject_storage():
    import gradio as gr
    demo = app.build_ui()
    texts = [b.value for b in demo.blocks.values() if isinstance(b, gr.Markdown)]
    assert any("Failed generations may be stored privately to improve quality." in t
               for t in texts)
