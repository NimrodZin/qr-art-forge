"""m2-12: repair wired into run_forge. Rows refer to steps/m2-12/spec.md §2 (A1–A12)."""
import importlib
import io
import pathlib

import pytest
from PIL import Image

import app
from qrbuild import make_qr
from validator import summary_line

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAY = "nimrodzin.com"
ENC = "https://nimrodzin.com"
GOOD = make_qr(ENC)
BAD = Image.new("RGB", (768, 768), (90, 90, 90))
SEED = 7
GATE_LINE = '        if v["pass"]:  # THE GATE — the only way into the gallery'


def rp():
    """The module under test; imported per test so each test fails on its own while it is missing."""
    return importlib.import_module("repair")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("REJECTS_REPO", raising=False)
    monkeypatch.delenv("QRAF_REPAIR", raising=False)


def img(rgb):
    return Image.new("RGB", (768, 768), rgb)


def png(im):
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def vres(passed, zx):
    """A full validate()-shaped result; zx = (full, small, tilt)."""
    results = {c: {"zx": z, "cv": False, "hits": ["LA@S0"] if z else [], "hit_count": int(z)}
               for c, z in zip(("full", "small", "tilt"), zx)}
    return {"pass": passed, "score": sum(zx), "max": 3, "results": results, "thin": False}


NEAR = vres(False, (True, False, False))       # score 1, fails small
NEAR2 = vres(False, (True, False, True))       # score 2
FAIL_R = vres(False, (False, True, False))     # repaired, still failing
PASS_V = vres(True, (True, True, False))


class World:
    """Fake validate keyed on object identity, recording every image it is shown."""

    def __init__(self, monkeypatch, table):
        self.table = table
        self.seen = []
        self.returned = []
        real = app.validate

        def fake(im, payload):
            assert payload == ENC
            self.seen.append(im)
            for obj, res in self.table:
                if im is obj:
                    break
            else:
                res = real(im, payload)
            self.returned.append((im, res))
            return res
        monkeypatch.setattr(app, "validate", fake)

    def passed_objects(self):
        return [im for im, res in self.returned if res["pass"]]


def recording_pipes(gen_imgs, rescue_img):
    calls = {"gen": [], "rescue": []}

    def gen(*a, **k):
        calls["gen"].append((a, k))
        return list(gen_imgs)

    def rescue(*a, **k):
        calls["rescue"].append((a, k))
        return rescue_img
    return {"gen": gen, "rescue": rescue}, calls


def spy_repair(monkeypatch, returns):
    """Replace repair.repair; `returns` maps candidate identity → (image, k) or is a callable."""
    calls = []

    def fake(*a, **k):
        calls.append((a, k))
        return returns(a[0]) if callable(returns) else returns
    monkeypatch.setattr(rp(), "repair", fake)
    return calls


def capture_archive(monkeypatch):
    seen = {"records": None}

    def fake(records):
        seen["records"] = records
        return "ARCHIVE-LINE"
    monkeypatch.setattr(app, "archive_rejects", fake)
    return seen


def labels(seen):
    return [p.rsplit("/", 1)[1][:-len(".png")] for p, *_ in seen["records"]]


def tags(report):
    """The per-seed report lines (between the header block and the archive line)."""
    return [ln for ln in report.splitlines() if ln.startswith("seed ")]


def run(pipes, batch=1, rescue=True, **kw):
    return app.run_forge(PAY, "p", batch, 1.35, 25, 7, rescue, SEED, pipes=pipes, **kw)


# ---------------------------------------------------------------- A1: QRAF_REPAIR=0 is main's behaviour
@pytest.mark.parametrize("rescue_on", [True, False])
def test_a1_disabled_is_mains_behaviour(monkeypatch, rescue_on):
    monkeypatch.setenv("QRAF_REPAIR", "0")

    def boom(*a, **k):
        raise AssertionError("repair called while QRAF_REPAIR=0")
    monkeypatch.setattr(rp(), "repair", boom)
    cand, resc = img((60, 70, 80)), img((61, 71, 81))
    world = World(monkeypatch, [(cand, NEAR), (resc, FAIL_R)])
    seen = capture_archive(monkeypatch)
    pipes, calls = recording_pipes([GOOD, BAD, cand], resc)
    surv, report, ctrl = run(pipes, batch=3, rescue=rescue_on)

    by_obj = {id(im): res for im, res in world.returned}
    lines = [f"seed {SEED}: " + summary_line(by_obj[id(GOOD)]),
             f"seed {SEED + 1}: " + summary_line(by_obj[id(BAD)]),
             f"seed {SEED + 2}: " + summary_line(NEAR)
             + ((" → rescue " + summary_line(FAIL_R)) if rescue_on else "")]
    expected = (f"1/3 passed. Encoded: {ENC}\n"
                "Always test on a real phone before publishing.\n\n"
                + "\n".join(lines + ["ARCHIVE-LINE"]))
    assert report == expected
    assert "repair" not in report
    assert [im for im, _ in surv] == [GOOD] and surv[0][0] is GOOD
    want = [f"seed{SEED + 1}", f"seed{SEED + 2}"] + ([f"seed{SEED + 2}-rescue"] if rescue_on else [])
    assert labels(seen) == want
    assert len(calls["rescue"]) == (1 if rescue_on else 0)


# ---------------------------------------------------------------- A2: a pass is never repaired
def test_a2_passing_candidate_not_repaired(monkeypatch):
    calls = spy_repair(monkeypatch, (BAD, 5))
    pipes, pc = recording_pipes([GOOD], BAD)
    surv, report, _ = run(pipes)
    assert calls == []
    assert pc["rescue"] == []
    assert len(surv) == 1 and surv[0][0] is GOOD
    assert tags(report) == [f"seed {SEED}: " + summary_line(app.validate(GOOD, ENC))]


# ---------------------------------------------------------------- A3: score 0 is neither repaired nor rescued
def test_a3_score_zero_not_repaired(monkeypatch):
    calls = spy_repair(monkeypatch, (GOOD, 5))
    pipes, pc = recording_pipes([BAD], GOOD)
    surv, report, _ = run(pipes)
    assert calls == []
    assert pc["rescue"] == []
    assert surv == []
    v = app.validate(BAD, ENC)
    assert v["score"] == 0
    assert tags(report) == [f"seed {SEED}: " + summary_line(v)]


# ---------------------------------------------------------------- A4: passing repair wins, rescue skipped
def test_a4_passing_repair_is_the_survivor(monkeypatch):
    cand, rep = img((60, 70, 80)), img((62, 72, 82))
    world = World(monkeypatch, [(cand, NEAR2), (rep, PASS_V)])
    calls = spy_repair(monkeypatch, (rep, 5))
    seen = capture_archive(monkeypatch)
    pipes, pc = recording_pipes([cand], GOOD)
    surv, report, ctrl = run(pipes)
    assert len(calls) == 1
    (a, k), = calls
    assert len(a) == 2 and a[0] is cand and a[1] is ctrl and k == {}
    assert pc["rescue"] == []
    assert len(surv) == 1 and surv[0][0] is rep
    assert any(im is rep and res["pass"] for im, res in world.returned)
    assert tags(report) == [f"seed {SEED}: " + summary_line(NEAR2)
                            + " → repair 5: " + summary_line(PASS_V)]
    assert labels(seen) == [f"seed{SEED}"]
    assert seen["records"][0][1] == png(cand)


# ---------------------------------------------------------------- A5: failed repair → rescue as on main
def _main_rescue_call(cand, ctrl, negative=app.NEG, **ref):
    return (("p", cand, ctrl, 1.35, 25, 7.0, SEED), {"negative": negative, **ref})


def test_a5_failed_repair_then_rescue_passes(monkeypatch):
    cand, rep, resc = img((60, 70, 80)), img((62, 72, 82)), img((64, 74, 84))
    World(monkeypatch, [(cand, NEAR), (rep, FAIL_R), (resc, PASS_V)])
    spy_repair(monkeypatch, (rep, 5))
    seen = capture_archive(monkeypatch)
    pipes, pc = recording_pipes([cand], resc)
    surv, report, ctrl = run(pipes)
    assert len(pc["rescue"]) == 1
    (a, k), = pc["rescue"]
    (wa, wk) = _main_rescue_call(cand, ctrl)
    assert a[1] is cand and a[2] is ctrl
    assert a == wa and k == wk
    assert len(surv) == 1 and surv[0][0] is resc
    assert tags(report) == [f"seed {SEED}: " + summary_line(NEAR) + " → repair 5: "
                            + summary_line(FAIL_R) + " → rescue " + summary_line(PASS_V)]
    assert labels(seen) == [f"seed{SEED}"]
    assert all(b != png(rep) for _, b, _ in seen["records"])


# ---------------------------------------------------------------- A6: failed repair, failed rescue
def test_a6_failed_repair_and_rescue(monkeypatch):
    cand, rep, resc = img((60, 70, 80)), img((62, 72, 82)), img((64, 74, 84))
    World(monkeypatch, [(cand, NEAR), (rep, FAIL_R), (resc, FAIL_R)])
    spy_repair(monkeypatch, (rep, 5))
    seen = capture_archive(monkeypatch)
    pipes, pc = recording_pipes([cand], resc)
    surv, report, _ = run(pipes)
    assert surv == []
    assert len(pc["rescue"]) == 1
    assert labels(seen) == [f"seed{SEED}", f"seed{SEED}-rescue"]
    assert seen["records"][0][1] == png(cand) and seen["records"][1][1] == png(resc)
    assert all(b != png(rep) for _, b, _ in seen["records"])


# ---------------------------------------------------------------- A7: k == 0 → not validated, rescue as main
def test_a7_zero_modules_touched(monkeypatch):
    cand, x, resc = img((60, 70, 80)), img((62, 72, 82)), img((64, 74, 84))
    world = World(monkeypatch, [(cand, NEAR), (x, PASS_V), (resc, PASS_V)])
    spy_repair(monkeypatch, (x, 0))
    pipes, pc = recording_pipes([cand], resc)
    surv, report, ctrl = run(pipes)
    assert all(im is not x for im in world.seen)
    assert len(pc["rescue"]) == 1
    (a, k), = pc["rescue"]
    assert a[1] is cand and (a, k) == _main_rescue_call(cand, ctrl)
    assert len(surv) == 1 and surv[0][0] is resc
    (tag,) = tags(report)
    assert " → repair 0: unchanged" in tag
    assert tag == (f"seed {SEED}: " + summary_line(NEAR) + " → repair 0: unchanged"
                   + " → rescue " + summary_line(PASS_V))


# ---------------------------------------------------------------- A8: repair runs with rescue off
def test_a8_rescue_off_still_repairs(monkeypatch):
    cand, rep = img((60, 70, 80)), img((62, 72, 82))
    World(monkeypatch, [(cand, NEAR), (rep, PASS_V)])
    calls = spy_repair(monkeypatch, (rep, 3))
    pipes, pc = recording_pipes([cand], GOOD)
    surv, report, _ = run(pipes, rescue=False)
    assert len(calls) == 1
    assert pc["rescue"] == []
    assert len(surv) == 1 and surv[0][0] is rep
    assert tags(report) == [f"seed {SEED}: " + summary_line(NEAR) + " → repair 3: "
                            + summary_line(PASS_V)]


def test_a8_rescue_off_failed_repair_drops_candidate(monkeypatch):
    cand, rep = img((60, 70, 80)), img((62, 72, 82))
    World(monkeypatch, [(cand, NEAR), (rep, FAIL_R)])
    calls = spy_repair(monkeypatch, (rep, 3))
    pipes, pc = recording_pipes([cand], GOOD)
    surv, _, _ = run(pipes, rescue=False)
    assert len(calls) == 1 and pc["rescue"] == [] and surv == []


# ---------------------------------------------------------------- A9: batch invariants
def test_a9_mixed_batch(monkeypatch):
    c1, c2 = img((60, 70, 80)), img((61, 71, 81))
    r1, r2, resc = img((62, 72, 82)), img((63, 73, 83)), img((64, 74, 84))
    world = World(monkeypatch, [(c1, NEAR), (c2, NEAR2), (r1, PASS_V), (r2, FAIL_R),
                                (resc, FAIL_R)])
    calls = spy_repair(monkeypatch, lambda im: (r1, 4) if im is c1 else (r2, 6))
    pipes, _ = recording_pipes([GOOD, c1, c2], resc)
    surv, report, _ = run(pipes, batch=3)
    firsts = [a[0] for a, _ in calls]
    assert all(sum(f is c for f in firsts) <= 1 for c in (GOOD, c1, c2))
    assert all(f is not GOOD for f in firsts)
    passed = world.passed_objects()
    assert all(any(s is p for p in passed) for s, _ in surv)
    assert [s for s, _ in surv] == [GOOD, r1] and surv[1][0] is r1
    assert report.startswith(f"{len(surv)}/3 passed.")


# ---------------------------------------------------------------- A10: env read per call
def test_a10_env_read_per_run_forge_call(monkeypatch):
    cand, rep = img((60, 70, 80)), img((62, 72, 82))
    World(monkeypatch, [(cand, NEAR), (rep, PASS_V)])
    calls = spy_repair(monkeypatch, (rep, 5))
    pipes, _ = recording_pipes([cand], GOOD)
    monkeypatch.setenv("QRAF_REPAIR", "0")
    surv, report, _ = run(pipes, rescue=False)
    assert calls == [] and surv == [] and "repair" not in report
    monkeypatch.delenv("QRAF_REPAIR")
    surv, _, _ = run(pipes, rescue=False)
    assert len(calls) == 1 and surv[0][0] is rep


# ---------------------------------------------------------------- A11: reference / negative pass-through
def test_a11_reference_and_negative(monkeypatch):
    cand, rep, resc = img((60, 70, 80)), img((62, 72, 82)), img((64, 74, 84))
    ref = Image.new("RGB", (64, 64), (200, 10, 10))
    World(monkeypatch, [(cand, NEAR), (rep, FAIL_R), (resc, PASS_V)])
    calls = spy_repair(monkeypatch, (rep, 5))
    pipes, pc = recording_pipes([cand], resc)
    _, _, ctrl = run(pipes, negative="people", reference=ref, reference_scale=0.7)
    (a, k), = calls
    assert len(a) == 2 and a[0] is cand and a[1] is ctrl and k == {}
    (ra, rk), = pc["rescue"]
    wa, wk = _main_rescue_call(cand, ctrl, negative=app.NEG + ", people",
                               reference=ref, reference_scale=0.7)
    assert ra == wa and rk == wk and rk["reference"] is ref


# ---------------------------------------------------------------- repair adds no progress call
def test_repair_adds_no_progress_call(monkeypatch):
    cand, rep = img((60, 70, 80)), img((62, 72, 82))
    World(monkeypatch, [(cand, NEAR), (rep, PASS_V)])
    calls = spy_repair(monkeypatch, (rep, 5))
    ticks = []
    pipes, _ = recording_pipes([cand, GOOD], GOOD)
    run(pipes, batch=2, progress=lambda *a, **k: ticks.append((a, k)))
    assert len(calls) == 1
    assert len(ticks) == 1 + 2  # main: one "Generating batch" + one "Testing i/n" per candidate


# ---------------------------------------------------------------- real repair end to end (BAD stays out)
def test_real_repair_of_flat_grey_cannot_reach_gallery(monkeypatch):
    rp()
    near = vres(False, (True, False, False))
    real = app.validate
    monkeypatch.setattr(app, "validate", lambda im, p: near if im is BAD else real(im, p))
    seen = capture_archive(monkeypatch)
    pipes, _ = recording_pipes([BAD], img((95, 95, 95)))
    surv, report, _ = run(pipes)
    assert surv == []
    (tag,) = tags(report)
    assert " → repair " in tag and " → rescue " in tag
    assert labels(seen) == [f"seed{SEED}", f"seed{SEED}-rescue"]


# ---------------------------------------------------------------- A12: the gate line
def test_a12_gate_line_is_unique_and_owns_the_gallery():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    assert lines.count(GATE_LINE) == 1
    assert src.count("survivors.append") == 1
    i = lines.index(GATE_LINE)
    assert "survivors.append(" in lines[i + 1]
    assert lines[i + 1].startswith(" " * 12)
    assert "import repair" in src and "repair.repair(" in src
