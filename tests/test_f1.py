"""F1 phone-truth set (02 v0.5): the validator against the phone results of run 20261017-143330.

Marked `f1`; skipped unless the git-ignored run folder exists (PC only; CI has no local/).
"""
import csv
import functools
import json
from pathlib import Path

import pytest
from PIL import Image

from validator import validate

RUN = Path(__file__).resolve().parent.parent / "local" / "f1" / "20261017-143330"
pytestmark = [pytest.mark.f1,
              pytest.mark.skipif(not RUN.is_dir(), reason=f"f1 test: needs the F1 run folder {RUN}")]

THIN_TILT_ONLY = [("photoreal_s1.1_plain_12348_4.png", ["GH@S2"]),    # read 3/3 on iPhone and Android
                  ("dreamshaper_s1.1_plain_12346_2.png", ["LA@S2"])]  # same; v0.5 rejects them all the same


def payload():
    return json.loads((RUN / "run.json").read_text(encoding="utf-8"))["payload"]


@functools.lru_cache(maxsize=None)
def check(name):
    return validate(Image.open(RUN / name), payload())


@pytest.mark.parametrize("name,small_hits", THIN_TILT_ONLY)
def test_thin_tilt_only_rejects_fail_again(name, small_hits):  # spec row 23
    v = check(name)
    assert v["pass"] is False and v["thin"] is True and v["score"] == 2
    assert v["results"]["full"]["zx"] and not v["results"]["tilt"]["zx"]
    assert v["results"]["small"]["hits"] == small_hits


def test_tilt_only_reject_with_margin_on_small_still_passes():  # spec row 24; read 3/3 on iPhone and Android
    v = check("dreamshaper_s1.1_dappled_12348_4.png")
    assert v["pass"] is True and v["thin"] is False and v["score"] == 2
    assert not v["results"]["tilt"]["zx"] and v["results"]["small"]["hit_count"] == 3


@pytest.mark.parametrize("name", ["photoreal_s1.1_plain_12348_4_rescued.png",
                                  "dreamshaper_s1.1_plain_12346_2_rescued.png"])
def test_rescued_versions_of_the_thin_rejects_pass(name):  # spec row 25
    v = check(name)
    assert v["pass"] is True and v["thin"] is False


def test_strength_0_9_still_fails_with_score_0():
    v = check("photoreal_s0.9_plain_12345_1.png")                # failed on both phones
    assert v["pass"] is False and v["score"] == 0


def test_thin_small_is_flagged_and_fails():  # spec row 22
    v = check("photoreal_s1.1_plain_12347_3.png")                # small=LA@S2 only; failed on iPhone at 768 px
    assert v["pass"] is False and v["thin"] is True and v["score"] == 3
    assert v["results"]["small"]["hits"] == ["LA@S2"]


def manifest_rows():
    if not RUN.is_dir():
        return []
    with open(RUN / "manifest.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


ROWS = manifest_rows()


@pytest.mark.parametrize("row", ROWS, ids=[r["file"] for r in ROWS])
def test_hits_match_f1_batch_encoding(row):
    # local/f1_batch.py's hits column: "full=LA@S0+GH@S2;small=-;tilt=..."
    v = check(row["file"])
    got = ";".join(f"{c}={'+'.join(r['hits']) or '-'}" for c, r in v["results"].items())
    assert got == row["hits"]
    assert int(v["score"]) == int(row["score"])


DEFAULT_STRENGTH = [r["file"] for r in ROWS if r["strength"] == "1.35"]


def test_default_strength_set_is_sixteen_images():
    assert len(DEFAULT_STRENGTH) == 16


@pytest.mark.parametrize("name", DEFAULT_STRENGTH)
def test_default_strength_keeps_passing_with_margin(name):  # spec row 26
    v = check(name)
    assert v["pass"] is True and v["thin"] is False
    assert v["results"]["small"]["hit_count"] >= 2


def test_exactly_three_of_the_manifest_are_thin():  # spec row 27
    assert len(ROWS) == 53
    assert {r["file"] for r in ROWS if check(r["file"])["thin"]} == {
        "photoreal_s1.1_plain_12347_3.png",
        "photoreal_s1.1_plain_12348_4.png",
        "dreamshaper_s1.1_plain_12346_2.png"}
