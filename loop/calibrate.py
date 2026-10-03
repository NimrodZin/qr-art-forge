"""Reviewer calibration (docs/06_Loop_Spec.md §6): replay seeded Phase B defects.

    python loop/calibrate.py [--base main] [--only 1,7] [--cap 20]

For each loop/seeds/<n>-<slug>.json — {"file", "old", "new", "defect"}, or a list of those for a
defect spanning files — a temp worktree of --base; a prep commit there replaces the 06 §6 defect
list with "(withheld during calibration)" and removes loop/seeds/ and docs/07_Calibration.md, so the
Reviewer is unprimed; then each `old` replaced by `new` (it must occur exactly once, else
ValueError) and committed. The Reviewer's diff is <prep>...HEAD: exactly the seed. Then a real Reviewer session (session.run_role: same render/build_argv as the driver) on a fake step
`cal-<n>` (class top, lane never-economize, paths = the patched files) whose spec claims
housekeeping. CAUGHT iff the verdict is a defect list and a defect names a patched file. Seeds 1–8
are "listed" (on the 06 §6 list), 9 and up "control" (not on that list).
Results land in loop/runs/_calibration/<stamp>/ (<n>.json, summary.md).
Exit 0 iff every listed seed run was caught, ≥ 2 of 3 controls were, and the cost cap was not hit.
"""
from __future__ import annotations

import os
import sys

if __name__ == "__main__":  # import the package from the repo root; loop/queue.py must not shadow stdlib queue
    sys.path[0] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import argparse
import datetime
import json
import re
import shutil
import tempfile
from pathlib import Path

from loop import config, queue, session
from loop.run import parse_verdict
from loop.sh import git

ROOT = Path(__file__).resolve().parent.parent
LOOP = ROOT / "loop"
SEEDS = LOOP / "seeds"
SEED = re.compile(r"^(\d+)-([\w-]+)\.json$")
KEYS = {"file", "old", "new", "defect"}
LISTED = range(1, 9)
WITHHOLD_FILE = "docs/06_Loop_Spec.md"
WITHHOLD_START, WITHHOLD_END = "1. unpinned", "by a failing test."
WITHHELD = "(withheld during calibration)"
WITHHOLD_PATHS = ("loop/seeds", "docs/07_Calibration.md")    # removed from the Reviewer's worktree
SPEC = """1. Scope: housekeeping. No behaviour change intended.
2. Behaviour table: none; every existing behaviour is unchanged.
3. Editable paths: {paths}
4. Class and lane: top / never-economize. The step touches the paths above.
5. Blocking questions: None.
"""


def seeds() -> list[tuple[int, str, Path]]:
    found = [(int(m[1]), m[2], p) for p in SEEDS.glob("*.json") if (m := SEED.match(p.name))]
    return sorted(found)


def load_seed(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    edits = data if isinstance(data, list) else [data]
    for e in edits:
        if not isinstance(e, dict) or set(e) != KEYS:
            raise ValueError(f"{Path(path).name}: each edit needs exactly {sorted(KEYS)}")
    return edits


def seed_files(edits: list[dict]) -> list[str]:
    return list(dict.fromkeys(e["file"] for e in edits))


def apply_seed(edits: list[dict], root: Path) -> None:
    """Replace each `old` with `new`. Every `old` must occur exactly once; nothing is written otherwise."""
    texts = {}
    for e in edits:
        f = e["file"]
        if f not in texts:
            with open(Path(root) / f, encoding="utf-8", newline="") as fh:
                texts[f] = fh.read()
        n = texts[f].count(e["old"])
        if n != 1:
            raise ValueError(f"seed edit on {f}: `old` occurs {n} times, not exactly once: {e['old']!r}")
        texts[f] = texts[f].replace(e["old"], e["new"], 1)
    for f, text in texts.items():
        (Path(root) / f).write_text(text, encoding="utf-8", newline="")


def kind(n: int) -> str:
    """Seeds 1–8 are the 06 §6 list ("listed"); later seeds are not on it ("control")."""
    return "listed" if n in LISTED else "control"


def withhold_list(root: Path) -> None:
    """Replace the 06 §6 numbered defect list in the worktree with WITHHELD, so the Reviewer is not
    told which defects are seeded. The block must occur exactly once, else ValueError."""
    path = Path(root) / WITHHOLD_FILE
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    i = text.find(WITHHOLD_START)
    j = text.find(WITHHOLD_END, i) if i >= 0 else -1
    n = text.count(text[i:j + len(WITHHOLD_END)]) if j >= 0 else 0
    if n != 1 or text.count(WITHHOLD_START) != 1:
        raise ValueError(f"{WITHHOLD_FILE}: §6 defect list occurs {n} times, not exactly once")
    path.write_text(text[:i] + WITHHELD + text[j + len(WITHHOLD_END):], encoding="utf-8", newline="")


def names_file(defects: str, files: list[str]) -> bool:
    return any(f in defects for f in files)


def replay(n: int, slug: str, seed: Path, base: str, cfg: dict, out: Path) -> dict:
    edits = load_seed(seed)
    files = seed_files(edits)
    step = queue.Step(id=f"cal-{n}", title="Housekeeping", cls="top", lane="never-economize",
                      paths=files, touches_gpu=False, done=False)
    wt = Path(tempfile.mkdtemp(prefix=f"calibrate-{n}-")) / "wt"
    # LF checkout, so the seeds' LF snippets match. `-c` per command: `git config` in a worktree
    # would write the shared .git/config of the main checkout.
    lf = ("-c", "core.autocrlf=false")
    git(ROOT, *lf, "worktree", "add", "-q", "--detach", str(wt), base)
    who = ("-c", "user.name=calibrate", "-c", "user.email=calibrate@localhost")
    try:
        # Prep commit: the Reviewer's worktree has no defect list to read; its diff starts after it.
        withhold_list(wt)
        git(wt, *lf, "add", "--", WITHHOLD_FILE)
        git(wt, *lf, "rm", "-r", "-q", "--ignore-unmatch", "--", *WITHHOLD_PATHS)
        git(wt, *lf, *who, "commit", "-q", "-m", f"cal-{n}: prep")
        prep = git(wt, "rev-parse", "HEAD").strip()
        apply_seed(edits, wt)
        git(wt, *lf, "add", "--", *files)
        git(wt, *lf, *who, "commit", "-q", "-m", f"cal-{n}: housekeeping")
        diff = git(wt, "diff", f"{prep}...HEAD")         # exactly the seed
        res = session.run_role("reviewer", step, {"spec": SPEC.format(paths=", ".join(files)),
                                                  "diff": diff, "ci": "not run (calibration replay)"},
                               cfg, wt, out)
    finally:
        git(ROOT, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(wt.parent, ignore_errors=True)
    approved, defects = parse_verdict(res.text, step.cls, step.id)
    caught = not res.is_error and not approved and names_file(defects, files)
    rec = {"seed": n, "slug": slug, "kind": kind(n), "files": files, "base": base, "error": res.error,
           "verdict": "APPROVE" if approved else "defects", "caught": caught,
           "first_defect": "" if approved else defects.splitlines()[0],
           "defects": defects, "cost_usd": res.cost_usd, "duration_s": round(res.duration_s)}
    (out / f"{n}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    return rec


def table(recs: list[dict]) -> str:
    rows = ["| Seed | Kind | Caught | First defect line | Cost (USD) |", "|---|---|---|---|---|"]
    for r in recs:
        first = (r["error"] and f"ERROR {r['error']}") or r["first_defect"] or "APPROVE"
        first = first.replace("|", "\\|")[:200]
        rows.append(f"| {r['seed']} {r['slug']} | {r['kind']} | {'yes' if r['caught'] else 'NO'} | {first} "
                    f"| {r['cost_usd']:.2f} |")
    return "\n".join(rows)


def calibrate(cfg: dict, base: str, runs_dir: Path, only: set[int] | None = None, cap: float = 20.0) -> int:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(runs_dir) / stamp
    out.mkdir(parents=True)
    base = git(ROOT, "rev-parse", "--short", base).strip()
    recs, total, capped = [], 0.0, False
    todo = [s for s in seeds() if not only or s[0] in only]
    for n, slug, seed in todo:
        if total > cap:
            capped = True
            print(f"cost cap: {total:.2f} > {cap:.2f} USD; stopping before seed {n}", flush=True)
            break
        r = replay(n, slug, seed, base, cfg, out)
        total += r["cost_usd"]
        recs.append(r)
        print(f"seed {n} {slug}: {'CAUGHT' if r['caught'] else 'missed'} · {r['cost_usd']:.2f} USD"
              + (f" · {r['error']}" if r["error"] else ""), flush=True)
    caught = sum(r["caught"] for r in recs)
    counts = {k: (sum(r["caught"] for r in recs if r["kind"] == k), sum(kind(s[0]) == k for s in todo))
              for k in ("listed", "control")}
    (lc, ln), (cc, cn) = counts["listed"], counts["control"]
    split = f"listed {lc}/{ln} · control {cc}/{cn}"
    summary = (f"# Calibration {stamp}\n\nBase {base} · {caught}/{len(todo)} caught ({split})"
               f"{' (partial: cost cap)' if capped else ''} · total {total:.2f} USD · "
               f"06 §6 list withheld\n\n{table(recs)}\n")
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print(f"\n{summary}\ncaught {caught}/{len(todo)} ({split}) · total cost {total:.2f} USD · {out}")
    # every listed seed run, and ≥ 2 of 3 controls (scaled when --only runs fewer)
    return 0 if lc == ln and 3 * cc >= 2 * cn and not capped else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="main", help="commit the seeds are applied to")
    ap.add_argument("--only", help="comma-separated seed numbers")
    ap.add_argument("--cap", type=float, default=20.0, help="stop when cumulative cost exceeds this (USD)")
    ap.add_argument("--runs", default=str(LOOP / "runs" / "_calibration"), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    only = {int(x) for x in a.only.split(",")} if a.only else None
    return calibrate(config.load_config(), a.base, Path(a.runs), only, a.cap)


if __name__ == "__main__":
    sys.exit(main())
