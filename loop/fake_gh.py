"""Fake `gh` for tests/test_loop.py and `run.py --dry-run`: records calls, touches nothing remote.

Env: FAKE_GH_LOG (append one JSON line per call) · FAKE_GH_CHECKS=pass|fail|pending (default pass) ·
FAKE_GH_NO_LABEL=<name> (`pr edit --add-label <name>` fails until `label create <name>` is in the log).
"""
import json
import os
import sys

argv = sys.argv[1:]
log = os.environ.get("FAKE_GH_LOG")
earlier = []
if log:
    if os.path.exists(log):
        with open(log, encoding="utf-8") as f:
            earlier = [json.loads(x)["argv"] for x in f if x.strip()]
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": argv}) + "\n")
missing = os.environ.get("FAKE_GH_NO_LABEL")
if argv[:2] == ["pr", "create"]:
    print("https://github.com/fake/repo/pull/7")
elif argv[:2] == ["pr", "checks"]:
    print(json.dumps([{"name": "test", "bucket": os.environ.get("FAKE_GH_CHECKS", "pass")}]))
elif argv[:2] == ["pr", "edit"] and missing and argv[-2:] == ["--add-label", missing] \
        and ["label", "create", missing] not in [a[:3] for a in earlier]:
    print(f"could not add label: '{missing}' not found", file=sys.stderr)
    sys.exit(1)
elif argv[:2] == ["run", "list"]:
    print(json.dumps([{"databaseId": 4242}]))
elif argv[:2] == ["run", "view"]:
    print("\n".join(f"fake failed log line {i}" for i in range(100)))
elif argv[:2] == ["issue", "list"]:
    print("[]")
elif argv[:2] == ["issue", "create"]:
    print("https://github.com/fake/repo/issues/8")
