"""The step queue: the `## Queue` section of docs/04_Build_Plan.md.

Line grammar, one step per line:
  - [ ] <id> · <title> · class=<top|long-pass|scoped|cheap> · lane=<ordinary|never-economize>
        · paths=<comma-separated> · touches_gpu=<yes|no>[ · <pr_url>]
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CLASSES = ("top", "long-pass", "scoped", "cheap")
LANES = ("ordinary", "never-economize")
SEP = " · "
ITEM = re.compile(r"^- \[(?P<mark>[ x])\] (?P<body>.+?)\s*$")
FIELD = re.compile(r"^(class|lane|paths|touches_gpu)=(.*)$")


@dataclass
class Step:
    id: str
    title: str
    cls: str
    lane: str
    paths: list[str]
    touches_gpu: bool
    done: bool
    pr_url: str | None = None


def _section(lines: list[str]) -> range:
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "## Queue") + 1
    except StopIteration:
        return range(0)
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return range(start, end)


def _parse_line(line: str) -> Step | None:
    m = ITEM.match(line)
    if not m:
        return None
    parts = m["body"].split(SEP)
    kv, title, extra = {}, [], []
    for part in parts[1:]:
        f = FIELD.match(part)
        if f:
            kv[f[1]] = f[2].strip()
        elif kv:
            extra.append(part.strip())
        else:
            title.append(part)
    if set(kv) != {"class", "lane", "paths", "touches_gpu"} or kv["class"] not in CLASSES \
            or kv["lane"] not in LANES or kv["touches_gpu"] not in ("yes", "no") or not title:
        raise ValueError(f"bad queue line: {line!r}")
    return Step(id=parts[0].strip(), title=SEP.join(title).strip(), cls=kv["class"], lane=kv["lane"],
                paths=[p.strip() for p in kv["paths"].split(",") if p.strip()],
                touches_gpu=kv["touches_gpu"] == "yes", done=m["mark"] == "x",
                pr_url=extra[0] if extra else None)


def parse_queue(text: str) -> list[Step]:
    lines = text.splitlines()
    return [s for i in _section(lines) if (s := _parse_line(lines[i]))]


def next_step(plan: Path | str) -> Step | None:
    return next((s for s in parse_queue(Path(plan).read_text(encoding="utf-8")) if not s.done), None)


def mark_done(step_id: str, pr_url: str, plan: Path | str) -> None:
    plan = Path(plan)
    lines = plan.read_text(encoding="utf-8").splitlines(keepends=True)
    for i in _section([l.rstrip("\r\n") for l in lines]):
        s = _parse_line(lines[i].rstrip("\r\n"))
        if s and s.id == step_id and not s.done:
            eol = lines[i][len(lines[i].rstrip("\r\n")):]
            lines[i] = lines[i].rstrip("\r\n").replace("- [ ]", "- [x]", 1) + SEP + pr_url + eol
            plan.write_text("".join(lines), encoding="utf-8", newline="")
            return
    raise KeyError(f"no open queue step {step_id!r}")
