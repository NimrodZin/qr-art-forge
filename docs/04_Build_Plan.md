# 04 — Build Plan v0.1 (2026-09-23)

Every gate is the REAL-WORLD TEST from 00.

## M0 — Repo and contract (manual, Phase B step 1)
Repo with docs/, CLAUDE.md, the Space files, pytest for validator and QR builder, GitHub Actions on push. Gate: none (no output yet). Exit: CI green on main.

## M1 — Space live (manual, Phase B step 2)
Space created and mirrored; first batch generated. Gate: 3/3 phone scans. Exit also requires Brief criteria 2 and 4 measured and recorded here.

## M2 — Quality loop (automated)
Tune P1/P2 from measured pass rates; UI polish behind "Advanced"; resolve O1. Gate: phone scan on a fresh batch + Brief criterion 3.
Steps: M2.1 gallery PNG (done) · M2.3 orchestrator (loop/) · M2.4 calibration (docs/07) · M2.5 pilot: OD 6(1) bleed canvas · then OD 8 IP-Adapter, OD 9 negative prompt, P5.

## M3 — Own-domain site (automated; after O2/O3 decided)
Front end on Nimrod's domain, backend API, rate limiting (Open Discussion 5). Gate: phone scan of a result served from that domain.

## Model classes (dated 2026-09-23)
- Top: all spec/ADR/review; never-economize list — validator (`validator.py`), payload (`qrbuild.py`), deploy config (`README.md` front-matter, `.github/`, Space secrets), gate rule (`forge()` gallery filter).
- Long-pass: M3 backend.
- Scoped: Gradio UI, tests from spec, CI.
- Cheap: none in v1.
The never-economize list is never downgraded.

## Gate log
- 2026-09-23 M1 (Space live): Space builds and generates (M1.3–M1.4). Validator v0.1 rejected 16/16 candidates across strengths 0.8/1.35/1.7/2.0 (peony, batch 4). Phone test of archived rejects (run 1382759530): 4/4 read on iPhone and Android; criterion 3 (poster): yes. Conclusion: validator too strict → 02 v0.2 (PR #7). Gate on v0.2 pending (ZeroGPU quota; resumes 2026-09-24).
- 2026-09-24 M1 gate PASSED on validator v0.2/v0.3: peony 4/4 shown, iPhone + Android 4/4, 21 s, poster yes. Criteria 1–5 met. Phase B complete.
- 2026-09-25 local env on RTX 4070 (local/REPORT-local.md): peony 64/64 over 16 batches, ~21 s headless; fisherman 9/12; finding → M2.1 (merged 9e5662f).
