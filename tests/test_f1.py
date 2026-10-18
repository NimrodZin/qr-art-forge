"""F1 phone-truth set (02 v0.4): the validator against the phone results of run 20261017-143330.

Marked `f1`; skipped unless the git-ignored run folder exists (PC only; CI has no local/).
"""
import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from validator import validate

RUN = Path(__file__).resolve().parent.parent / "local" / "f1" / "20261017-143330"
pytestmark = [pytest.mark.f1,
              pytest.mark.skipif(not RUN.is_dir(), reason=f"f1 test: needs the F1 run folder {RUN}")]

TILT_ONLY_REJECTS = ["photoreal_s1.1_plain_12348_4.png",       # read 3/3 on iPhone and Android
                     "dreamshaper_s1.1_plain_12346_2.png",
                     "dreamshaper_s1.1_dappled_12348_4.png"]


def payload():
    return json.loads((RUN / "run.json").read_text(encoding="utf-8"))["payload"]


def check(name):
    return validate(Image.open(RUN / name), payload())


@pytest.mark.parametrize("name", TILT_ONLY_REJECTS)
def test_tilt_only_rejects_now_pass(name):
    v = check(name)
    assert v["pass"] is True and v["score"] == 2
    assert v["results"]["full"]["zx"] and v["results"]["small"]["zx"] and not v["results"]["tilt"]["zx"]


def test_strength_0_9_still_fails_with_score_0():
    v = check("photoreal_s0.9_plain_12345_1.png")                # failed on both phones
    assert v["pass"] is False and v["score"] == 0


def test_thin_small_pass_is_flagged():
    v = check("photoreal_s1.1_plain_12347_3.png")                # small=LA@S2 only; failed on iPhone at 768 px
    assert v["pass"] is True and v["thin"] is True
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
