# 07 — Calibration v0.2 (2026-10-03)

Base: main at 22094c5 (06 v0.5). Supersedes v0.1 (c909e07, primed replay 8/8, mutation
stopped at 26/157, verdict NOT YET). Provenance: planner audit F4, chat 2026-10-03, PR #21
(hardening), PR #22 (this file + tests).

## 1. Reviewer replay — unprimed

`loop/calibrate.py --base main --cap 25`, run 20261003-180658. Each seed in a worktree whose
prep commit withholds the 06 §6 list and removes `docs/07` and `loop/seeds/`; the Reviewer's
diff is exactly the seed. Reviewer: claude-opus-5-5, read-only tools.

11/11 caught: listed 8/8, control 3/3. Total 16.17 USD (0.36–2.41 per seed; the 2.3–2.4 runs
read all of docs 00–06).

| Seed | Kind | Caught | Cost |
|---|---|---|---|
| 1 huggingface-hub-unpinned | listed | yes | 2.40 |
| 2 short-description-too-long | listed | yes | 2.41 |
| 3 gradio-4440-pydantic-unpinned | listed | yes | 2.34 |
| 4 sdk-version-mismatch | listed | yes | 0.81 |
| 5 gradio4-starlette-pin | listed | yes | 0.89 |
| 6 scheduler-no-algorithm-type | listed | yes | 1.15 |
| 7 validator-gates-on-opencv | listed | yes | 2.28 |
| 8 gallery-not-png | listed | yes | 0.44 |
| 9 no-tilt-condition | control | yes | 0.84 |
| 10 pass-rule-off-by-one | control | yes | 2.26 |
| 11 quiet-zone-2 | control | yes | 0.36 |

Caveat: every seed sits under a spec that claims "no behaviour change", so the catches test
diff-versus-spec plus contract reading. A spec that *authorises* the bad change is untested;
seed 12 (spec-authorised contract violation) is queued before any widening of the lane.

Earlier run 20261003-180246: 0/11, `claude` binary not on PATH after the 2.1.288 auto-update
(C:\Users\User\.local\bin). Zero cost. Follow-up: driver preflight logs `claude --version`.

## 2. Mutation testing

mutmut 2.5.1 on `validator.py`, `qrbuild.py`; runner
`pytest -x -q tests/test_validator.py tests/test_qrbuild.py`; mutants 28–157 run one at a time
under an external 10-minute kill (mutant 27 — blur sigma ×600 instead of ÷600 — cannot be killed
by mutmut's own timeout on Windows; counted as a timeout kill).

157 mutants · 134 non-equivalent · **134/134 killed** (120 in-run, 13 by the m2-11 tests, 1
timeout) · 23 equivalent · raw 134/157 = 85 %.

Equivalent (23), by reason:
- unreachable `except` branch (zxing installed): 4, 5, 6, 15
- tilt geometry not specified to the pixel (02: "mild perspective"): 51, 52, 53, 54, 60, 62, 63, 64
- borderValue 256 clamps to 255: 69, 70, 71
- canvas grey ±1, unspecified: 105, 106, 107
- message wording: 117, 131, 134
- box_size resized away: 137 · `fit=False` with `version=None` still best-fits: 139

Gaps closed in m2-11 (13), all tests in `tests/`: 121, 124 (scheme rules), 130 (80/81
boundary), 113 (None rejected), 103, 156 (768×768, centred), 140, 141 (module grid), 136 (quiet
zone = 4), 7 (SOFTEN_LEVELS), 12, 13, 18 (cv/zx decoders on blank and clean images).

## 3. Verdict against 06 §6

Replay: 8/8 listed and 3/3 controls, unprimed, one full run — met.
Mutation: 100 % of non-equivalent killed, every survivor triaged, every gap closed — met.

Verdict (Nimrod): yes — 2026-10-03, planner chat; lane opened in PR #23.
