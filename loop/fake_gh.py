"""Fake `gh` for tests/test_loop.py and `run.py --dry-run`: records calls, touches nothing remote.

Env: FAKE_GH_LOG (append one JSON line per call) · FAKE_GH_CHECKS=pass|fail|pending (default pass).
"""
import json
import os
import sys

argv = sys.argv[1:]
if os.environ.get("FAKE_GH_LOG"):
    with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv}) + "\n")
if argv[:2] == ["pr", "create"]:
    print("https://github.com/fake/repo/pull/7")
elif argv[:2] == ["pr", "checks"]:
    print(json.dumps([{"name": "test", "bucket": os.environ.get("FAKE_GH_CHECKS", "pass")}]))
elif argv[:2] == ["issue", "list"]:
    print("[]")
elif argv[:2] == ["issue", "create"]:
    print("https://github.com/fake/repo/issues/8")
