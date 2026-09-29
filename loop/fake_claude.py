"""Fake `claude -p` for tests/test_loop.py and `run.py --dry-run`. Reads the prompt on stdin,
acts out the role in cwd, prints claude-shaped JSON.

Env: FAKE_CLAUDE_LOG (append one JSON line per call) · FAKE_REVIEW=defects · FAKE_NO_HEADER=1 ·
FAKE_TESTER_GREEN=1 (tests pass before implementation) · FAKE_IMPL_ESCAPE=1 (implementer edits
tests/) · FAKE_ARCH_BLOCKED=1 (spec with a non-empty Blocking questions section) ·
FAKE_ROLE_BLOCKED=<role> (that role replies header + `BLOCKED: fake reason`, does nothing) ·
FAKE_MODEL=<id>[,<id>…] (modelUsage reports these instead of the --model argument) ·
FAKE_TESTER_NONE=1 (tester writes nothing) · FAKE_IMPL_NOOP=1 (implementer changes nothing) ·
FAKE_IMPL_RED=first|always (implementer's edit leaves the suite red on its first / every attempt) ·
FAKE_IMPL_UI=1 (implementer also adds app.py lines with label=, placeholder=, gr.Markdown() ·
FAKE_COST (default 0.01).
"""
import json
import os
import re
import sys
from pathlib import Path

HANDOVER = "\n\n## Handover\n- pytest -q: fake\n- Files changed: fake\n- Not certain: None\n- Deploy: none\n"


def field(prompt, name):
    return re.search(rf"^{name}: (.*)$", prompt, re.M).group(1).strip()


def main():
    prompt = sys.stdin.buffer.read().decode("utf-8")
    role = field(prompt, "Role").lower()
    step_id = field(prompt, "Step id")
    header = re.search(r"exactly this line, on line 1:\n(.+)", prompt).group(1).strip()
    paths = field(prompt, "Editable paths").split(",")
    if os.environ.get("FAKE_CLAUDE_LOG"):
        with open(os.environ["FAKE_CLAUDE_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"role": role, "argv": sys.argv[1:], "cwd": os.getcwd(),
                                "stdin_prompt": prompt}) + "\n")

    target = next(p for p in paths if not p.startswith(("tests", "docs", "steps")))
    marker = f"# loopfake {step_id}"
    safe_id = re.sub(r"\W", "_", step_id)
    test_file = Path("tests") / f"test_loopfake_{safe_id}.py"
    if os.environ.get("FAKE_ROLE_BLOCKED") == role:
        body = "BLOCKED: fake reason\n\nThe fake role stopped to report instead of doing its task."
    elif role == "architect":
        questions = "## 5. Blocking questions\nB1: fake question touching docs/02. Options: A or B. " \
            "Recommendation: A." if os.environ.get("FAKE_ARCH_BLOCKED") else "5. Blocking questions: None"
        body = f"## Scope\nFake spec for {step_id}: append `{marker}` to {target}.\n\n{questions}"
    elif role == "tester" and os.environ.get("FAKE_TESTER_NONE"):
        body = "The fake tester wrote no tests: nothing in the spec is testable."
    elif role == "implementer" and os.environ.get("FAKE_IMPL_NOOP"):
        body = "Nothing to change: the fake implementer found the work already done."
    elif role == "tester":
        test_file.parent.mkdir(exist_ok=True)
        check = "True" if os.environ.get("FAKE_TESTER_GREEN") else \
            f"{marker!r} in (Path(__file__).resolve().parents[1] / {target!r}).read_text()"
        test_file.write_text(f"from pathlib import Path\n\n\ndef test_loopfake():\n    assert {check}\n")
        body = "Tests written; red on main."
    elif role == "implementer":
        dest = test_file if os.environ.get("FAKE_IMPL_ESCAPE") else Path(target)
        first = re.search(r"^Defects from .*\n\(none\)$", prompt, re.M) is not None
        red = os.environ.get("FAKE_IMPL_RED")
        line = f"# loopfake-broken {step_id}" if red == "always" or (red == "first" and first) else marker
        if os.environ.get("FAKE_IMPL_UI"):
            line += '\nbox = gr.Textbox(label="Fake label", placeholder="fake hint")\ngr.Markdown("Fake UI note")'
        with open(dest, "a", encoding="utf-8") as f:
            f.write(f"\n{line}\n")
        body = f"Appended the marker to {dest.as_posix()}."
    else:
        body = f"1. Fake defect: {target}:1 does not do the thing." \
            if os.environ.get("FAKE_REVIEW") == "defects" else "APPROVE"

    text = ("" if os.environ.get("FAKE_NO_HEADER") else header + "\n") + body + HANDOVER
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "fake"
    models = os.environ.get("FAKE_MODEL", model).split(",")
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                      "session_id": f"fake-{role}", "num_turns": 1, "duration_ms": 1,
                      "total_cost_usd": float(os.environ.get("FAKE_COST", "0.01")),
                      "modelUsage": {m: {} for m in models}}))


if __name__ == "__main__":
    main()
