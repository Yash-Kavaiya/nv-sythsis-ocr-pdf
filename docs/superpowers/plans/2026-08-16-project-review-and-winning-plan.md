# Project Review + Winning-Idea Plan

**Date:** 2026-08-16
**Repo:** Synthetic OCR PDF Studio (nv-sythsis-ocr-pdf)
**Scope:** Full review of the NeMo-stage pipeline (Curator → Data Designer → Safe
Synthesizer → Evaluator, plus the LaTeX/PDF harness), then a concrete plan for
positioning this as a winning hackathon/grant submission.

---

# Part 1 — Project Review

## 1.1 What this is

A working end-to-end web app that generates **synthetic document datasets for OCR
training** and **evaluates a user's own OCR model** against them:

```
Seed (HuggingFace / sample / empty) + one prompt
  → NeMo Curator (clean, dedup, PII-scrub, web retrieval)
  → NeMo Data Designer (prompt → schema: doc type, theme, locale, currency, fields)
  → NeMo Safe Synthesizer (schema → ground-truth JSON, arithmetically exact)
  → LaTeX agent harness → PDF (tectonic/pdflatex or fpdf2) → page PNG
  → NeMo Evaluator (CER/WER, field accuracy, structure F1 vs your vision model)
```

Strengths that are real and worth keeping:

- **Guaranteed-correct ground truth.** Money fields are recomputed
  (`total = Σ items × qty`, `tax = subtotal × rate`), so every generated doc is
  arithmetically exact — the single most important property for OCR evals, and a
  genuine differentiator versus "paste random values" generators.
- **Honest offline fallback.** No API key → deterministic Faker pipeline still
  produces a complete dataset + PDFs. Zero-friction demo for judges.
- **LLM-repair agent loop for LaTeX** (`app/latex/harness.py`): render → validate
  (brace/env balance, unresolved vars) → LLM repair → safe fallback. This
  "agent harness" is a strong story beat.
- **Dual render path** (real LaTeX when installed, pixel-matched fpdf2 fallback)
  with PNG rasterization for vision models.
- **Clean eval contract** — 4 metrics, per-field diff table, upload-or-call model,
  multi-provider support (NVIDIA NIM / OpenAI / OpenRouter / Gemini / Anthropic /
  Azure / GitHub) with error bodies surfaced (tested).
- **Good hygiene**: gitignored `.env`, path-traversal guards in storage, flat
  `doc_i.*` artifacts kept for compatibility, a real design spec + implementation
  plan for the frontend already in `docs/`.

## 1.2 Current state snapshot (important!)

| Item | State |
|---|---|
| `main` branch | One-shot pipeline + legacy vanilla-JS frontend (`static/`) |
| Uncommitted work on `main` | QROTAID web-retrieval upgrade (`curator.py`, `designer.py`, new `web_retriever.py`), `run.sh`/`run.ps1`, README |
| `feature/nemo-e2e-frontend` branch | **Full React+Vite wizard already built** (5,805 insertions): per-stage APIs, NeMo Claw chat, stale-stage tracking, `tests/test_stages.py` + `tests/test_claw.py` — **not merged** |
| Tests | 4 pass (`test_error_surfacing.py` only; branch adds ~10 more) |
| Origin | `main` is 3 commits ahead of `origin/main` (docs + `.worktrees` ignore) |

**Bottom line: the two halves of this product live in two different branches.**
The flashy "winning" demo (wizard + Claw) is on `feature/nemo-e2e-frontend`;
the newest data-quality work (web retrieval) is uncommitted on `main`. The very
first action of any plan must be to reconcile these.

## 1.3 Stage-by-stage review

### NeMo Curator (`app/pipeline/curator.py`)

Good: NFKC normalization, exact + near + semantic dedup, quality filter, PII
scrub, per-stage report, and the new QROTAID stages (quality retrieval from the
web, ranking, organization, augmentation, integration).

Problems:

1. **The web-retrieval feature is dead code in the running app.** `app/main.py:86`
   calls `curator.curate(seed_records)` — no `prompt`, no `doc_type`, so
   `use_web_retrieval` never fires (prompt defaults to `""`). The QROTAID report
   keys don't appear in any live run. It only runs via `python -m app.pipeline.curator`.
2. `web_retriever.py` needs `OPENROUTER_API_KEY` (Perplexity via OpenRouter) or
   `SERP_API_KEY` — **undocumented** in README, silently degrades to empty when
   absent, and makes a live HTTP call inside the pipeline run with no cache.
3. `_extract_structured_fields` mapping only returns fields literally present in
   the LLM's `extracted_fields` JSON; quality of the retrieved data depends
   entirely on the Perplexity prompt.
4. The `curate()` signature change is backward-compatible but `main.py` was not
   updated to pass the new args (see #1).

### NeMo Data Designer (`app/pipeline/designer.py`)

Good: keyword doc-type inference, LLM-backed schema design with a clean JSON
contract, and new curated-record analysis (companies, items, currency, locale,
tax rates, payment terms) feeding the LLM prompt.

Problems:

1. **Same wiring gap.** `app/main.py:91` calls `design_schema(req.prompt, stats, llm, req.doc_type)` without `curated_records`, so the analysis/field-override machinery never runs in production.
2. `field_overrides` sets field `type` (e.g. `tax_rate: percent`, `payment_terms: choice:…`) but the Synthesizer ignores `pattern` and `common_values` — partial implementation, so overrides are only partly honored.
3. Locale detection keys off currency symbols in addresses — brittle (e.g. "$" defaults to `en_US` even for `en_AU`), and only 4 locales are ever detected.

### NeMo Safe Synthesizer (`app/pipeline/synthesizer.py`)

Good: LLM-first with Faker fallback, deterministic seeding, `_enforce_consistency`
recomputes money so ground truth is exact, `due_date` derived from `invoice_date`,
`card_last4` cleared for CASH/UPI.

Problems:

1. `_gen_field` handles a fixed type list; any `type` the Designer emits that
   isn't in that list silently falls to `fake.word()` — including `pattern`-typed
   overrides.
2. Faker locales beyond latin-1 break the **fpdf2 fallback renderer**: `_s()` in
   `app/pdfgen/fpdf_renderer.py` does `encode("latin-1", "replace")`, so ₹, €, £,
   é, 中文 all render as `?` in the PDF while the JSON ground truth keeps the
   real character — **ground truth and pixels disagree** exactly when the user
   picks an INR/EURO theme without a LaTeX engine installed. This is the
   highest-impact correctness bug in the product.
3. `company_style` "flavor" hack mangles vendor names in fallback mode
   (`record[key].split(',')[0].split(' and ')[0]` + first word of style).
4. No dataset diversity knobs (item count, value ranges, date ranges) — diversity
   is whatever the LLM/Faker gives.

### LaTeX agent harness + PDF (`app/latex/harness.py`, `app/pdfgen/`)

Good: strict-Jinja2 templates, validation with actionable errors, LLM repair with
attempt budget, engine auto-detect, PNG rasterization.

Problems:

1. Only **4 templates** (invoice/receipt/letter/form), single page, no tables with
   wrapped cells in LaTeX fallback, no multi-page docs.
2. Repair loop caps at 2 attempts and silently falls back to fpdf2 on failure —
   fine, but the manifest should record *why* (it records attempts, not errors).
3. `pdf_to_png` renders only page 1 at scale 2 — fine for now, limiting for
   multi-page or handwriting.

### NeMo Evaluator (`app/evals/`)

Good: 4 clean metrics (field accuracy, fuzzy, CER, WER, structure F1), per-field
diff, error surfacing with body text (tested), multi-provider, upload mode,
persisted + comparable across runs.

Problems:

1. **No cross-model comparison/leaderboard** — evals are stored but nothing ranks
   models against each other; this is where "evaluator" becomes a *story*.
2. `evaluate_doc` normalizes money strings by stripping `$` only — `₹1,234.50`
   won't match `1234.50` the same way (minor).
3. Metrics treat missing predicted keys as misses but don't report a *failure
   taxonomy* (which field classes fail: dates vs money vs names) — that taxonomy
   is exactly what a data flywheel needs.

### Frontend

- `main` = legacy static Studio + Eval Lab (functional, dated).
- `feature/nemo-e2e-frontend` = polished React wizard + Claw chat. **Merge it**;
  the legacy site can stay at `/legacy/`.

### Infra / tests / docs

- Good: filesystem storage with traversal guards, `run.ps1`/`run.sh` with `.env`
  sourcing, README covers env vars + API surface.
- Gaps: no tests for curator/designer/synthesizer internals on `main`; no tests
  for the new QROTAID code; web-retriever env vars undocumented; no CI config.

## 1.4 Defect list (fix in order)

| # | Severity | Where | Issue |
|---|---|---|---|
| D1 | **High** | `app/pdfgen/fpdf_renderer.py` `_s()` | latin-1 replace mangles ₹/€/£ in fallback PDFs → ground truth ≠ pixels |
| D2 | **High** | `app/main.py:86,91` | QROTAID + curated analysis never wired in — dead feature in live runs |
| D3 | **Med** | `README.md` | `OPENROUTER_API_KEY` / `SERP_API_KEY` undocumented |
| D4 | **Med** | `app/pipeline/synthesizer.py` | unknown field types silently become `fake.word()`; `pattern`/`common_values` overrides ignored |
| D5 | **Med** | `app/evals/metrics.py` | money normalization strips `$` only (₹/€ break exact match); no failure taxonomy |
| D6 | **Low** | `app/pipeline/designer.py` | locale detection is currency-symbol-driven, 4 locales max |
| D7 | **Low** | repo | main vs `feature/nemo-e2e-frontend` divergent — two halves of one product |
| D8 | **Low** | tests | no coverage for new curator/designer/synthesizer code on main |

## 1.5 How the real NVIDIA NeMo stack maps to this project

Checked the official docs for all four tools. Bottom line: **three of the four
are real, installable NVIDIA libraries, and none of them generate rendered
documents** — so this project's rendering core stays custom, but its data
stages can be genuinely grounded in NeMo. The pitch therefore flips from
"NeMo-style stages" to **"we orchestrate the real NeMo ecosystem around the
document-rendering core NeMo doesn't cover."**

| Real tool | What it actually is (official docs) | Fit to this project | Verdict |
|---|---|---|---|
| **NeMo Curator** (`nemo-curator`) | Open-source scalable curation across text/image/video/audio: GPU-accelerated pipelines, sharding, filtering, semantic dedup, ASR | Curate seed text + dedup generated images; heavy (Dask/RAPIDS, GPU, Linux) | Use for seed/image curation when available; keep the lightweight in-app curator as default |
| **NeMo Data Designer** (`pip install data-designer`) | LLM orchestration: declare columns (Sampler, LLMText…), preview, validate, create at scale; statistical diversity, field correlations, batching/parallelism, reproducible | This project's designer+synthesizer in one real library; works with `NVIDIA_API_KEY` (already set) | **Integrate as the scale-generation path** — closest fit, runs anywhere |
| **NeMo Safe Synthesizer** (`safe-synthesizer`) | Privacy-first synthetic tabular data: PII detect/replace, DP fine-tuning (Opacus/LoRA), vLLM inference, privacy+quality HTML report | Maps to the in-app PII-scrub + "safe" story; **needs Linux + A100-class GPU** for real runs | Keep in-app PII scrub as the always-on safety layer; document the real tool as the DP upgrade tier |
| **NeMo Evaluator** (`nel`) | LLM eval framework: environments, pluggable solvers, built-in benchmarks, **run compare (`nel compare`), statistical regression (McNemar), quality gates (GO/NO-GO)**, checkpoint/resume | Its *concepts* transfer; OCR eval stays custom | **Port the concepts**: compare, quality gate, regression — that's the flywheel rigor |

---

# Part 2 — The Winning Idea

## 2.1 The pitch (one paragraph)

> **Document AI is bottlenecked by data: real labeled documents are scarce,
> expensive, and privacy-risky. This project is the "one prompt → guaranteed-correct
> synthetic document dataset" flywheel built on the NeMo stage story — Curator
> cleans and retrieves real-world seeds, Data Designer shapes the schema, Safe
> Synthesizer generates arithmetically-exact ground truth, and the Evaluator
> closes the loop: OCR failures automatically re-seed the Curator to generate
> more targeted data, so the dataset gets *smarter* every time you eval.**

Why this wins a judge's heart:

1. **Real problem, measurable pain.** Labeled document data (invoices, receipts,
   forms) is the #1 cost in document AI. Nobody disputes it.
2. **A closed loop, not a tool.** Tools demo; *systems* win. "Generate → eval →
   generate again where it failed" is a flywheel story in 30 seconds.
3. **Full-stack, end-to-end demo.** One prompt in → JSON + LaTeX + PDF + PNG +
   eval scores out. No "it works on my machine" caveats.
4. **NVIDIA ecosystem alignment.** NIM-backed LLM design/synthesis/repair +
   NeMo-named stages + a natural slot for real NeMo Curator/Retriever later —
   exactly what NVIDIA-sponsored judging rewards.
5. **Dual-track narrative: offline works, online shines.** Judges can run the
   demo with no keys (deterministic) and still see the LLM path in screenshots.

## 2.2 The name

**"NeMo Document Data Flywheel"** — or keep the studio branding and call the demo
**"Synthetic OCR Studio: from one prompt to a trained, evaluated model."**

## 2.3 Demo script (5 minutes, memorizable)

1. **0:00 Hook.** "Training an OCR model today means paying humans to label
   invoices. Watch what one prompt does."
2. **0:20** Type `pharmacy invoices from Indian retailers with GST, in rupees`,
   hit **Run all** (wizard: Curator → Designer → Safe Synthesizer).
3. **0:50** Flip through stage reports live: dedup stats, detected currency ₹,
   locale `en_IN`, exact totals.
4. **1:30** Open 2–3 generated PDFs (thumbnails), show JSON next to PDF: totals
   match by construction.
5. **2:10** **The moment:** switch to Evaluator, run a real NIM vision model (or
   upload a baseline), see the per-field diff table.
6. **2:50** Click **Claw** → "why did money fields fail?" → Claw runs
   `suggest_fix`, re-runs synthesize with targeted field overrides, eval improves.
   *(This is the flywheel moment — rehearse it hard.)*
7. **4:00** Numbers: 50 docs in ~60s, exact ground truth, CER from X→Y after one
   loop. Close with the data-size argument: "1,000 labeled docs ≈ $2,000 and 2
   weeks. This is free and instant."

## 2.4 Execution plan (ordered; each phase shippable alone)

### Phase 0 — Reconcile the repo (half a day) — *prerequisite, do first*
- Commit the uncommitted `main` work (QROTAID, run scripts, README).
- Merge `feature/nemo-e2e-frontend` into `main`; resolve conflicts in README /
  run scripts / tests (the branch already has its own copies).
- Verify: `pytest`, `./run.sh`, one Run-all from the React UI, one eval upload.

### Phase 1 — Wire the new data quality (1 day) — *fixes D2, D3, D8*
- Pass `req.prompt` + inferred `doc_type` into `curator.curate(...)` in
  `app/main.py` (and the new `stages.run_curate` on the branch).
- Pass `curated` records into `designer.design_schema(..., curated_records=curated)`.
- Make web retrieval **non-blocking & cached**: run it in a thread with a
  timeout, cache results per `(prompt, doc_type)` hash in `data/cache/`, and add
  a `use_web_retrieval` checkbox in the Curator page (default on when keys set).
- Document `OPENROUTER_API_KEY` / `SERP_API_KEY` in README.
- Add unit tests for `curate()` with a mocked retriever (no network in CI).

### Phase 1b — Ground the stack in the real NeMo tools (1–2 days) — *the credibility play*

Flip the narrative from "NeMo-style stages" to **"we orchestrate the real NeMo
ecosystem around a document-rendering core NeMo doesn't cover"** (see §1.5).

1. **Real Data Designer as the scale generator.** Add an optional
   `generator: "data-designer"` mode: the in-app Designer's schema is translated
   to `DataDesignerConfigBuilder` columns (SamplerCategory for choice fields,
   LLMText for company/name/address/items seeded with the schema's theme +
   vocabulary); records come back validated and statistically diverse, then the
   existing LaTeX harness renders them unchanged. Works on this machine today
   with the NVIDIA key already set in `.env`; the current LLM/Faker synthesizer
   stays as the fallback.
2. **Real Curator for seed + image curation.** Document (and CI-gate, since it's
   Linux/Dask-heavy) a `curate_seed` job using `nemo-curator` text filters/dedup
   on the HuggingFace seed, plus image dedup/quality filtering on generated PNGs.
3. **Safe Synthesizer as the DP upgrade tier.** Export a `privacy_report`
   mirroring the real tool's PII-replacement report; document that true
   differential-privacy fine-tuning requires the GPU-backed `safe-synthesizer`
   package (Linux, A100-class) — positioned as the enterprise tier, not demoed.
4. **Evaluator rigor, ported.** In the in-app Evaluator add: **run comparison**
   (diff two evals, `nel compare` style), **quality gates** (GO/NO-GO on
   `fuzzy_field_accuracy ≥ 0.9`), and **statistical regression** (paired flip on
   per-doc scores) so "the dataset improved" is a *tested* claim.
5. **README + pitch stack diagram.** Custom core + real NeMo packages per phase,
   with a `requirements-optional.txt` for `data-designer` / `nemo-curator` /
   `safe-synthesizer` including platform notes.

### Phase 2 — Ground-truth == pixels (1 day) — *fixes D1, D4*
- Replace fpdf2's latin-1 `_s()` with a unicode-aware strategy: bundle a small
  DejaVu Sans subset TTF (MIT-licensed) with fpdf2, or map common currency
  symbols (₹ € £ ¥) to `?` *only if the JSON is also rendered with the same
  token* — no: the right fix is a real font. DejaVu Sans has full currency
  coverage and is one file.
- Guard the Synthesizer: unknown field types → explicit error in the report
  (not silent `fake.word()`); honor `pattern`/`common_values` for `percent`,
  `money`, `choice`, `id` types.
- Add a post-generation **consistency verifier** that re-checks every doc's math
  and emits a `verified: true` flag — the "guaranteed ground truth" claim becomes
  *checked*, not assumed.

### Phase 3 — The flywheel (the winning feature) (2 days)
- **Failure-taxonomy in Evaluator** (fixes D5): classify per-field misses into
  buckets — `money`, `date`, `name`, `id`, `items[*]`, `address` — and report
  the top failing buckets per run.
- **Targeted re-generation endpoint** `POST /api/runs/{id}/regenerate`:
  takes eval failures → bumps those fields in the Designer's
  `field_overrides` (e.g. more variety in `money` formats, new `choice:` values,
  degraded fonts for the failing class) → re-runs synthesize → returns new docs
  + previous vs new metric delta.
- **Model leaderboard** `GET /api/leaderboard`: aggregate persisted evals per
  `model_name`, ranked by `fuzzy_field_accuracy` — turns Eval Lab into a
  comparison story ("ours vs baseline").
- Wire **Claw** to drive the loop: `suggest_fix` becomes grounded in the failure
  taxonomy, not just `stage_error`.
- UI: on the Evaluator page, show "Generate more docs targeting: [money] [dates]"
  → one click does the loop. This is the demo moment in 2.3 step 6.

### Phase 4 — Realism (the credibility boost) (2–3 days)
- **Rendering degradation pipeline**: skew (≤3°), gaussian noise, blur, contrast,
  and font choice (bundle 2–3 free fonts) applied at PDF/PNG time; store the
  augmentation params in the manifest so evals stay reproducible. Real OCR
  training needs messy renders — this is what makes the dataset *useful*.
- More doc types if time: `payslip`, `bank statement`, `tax form`, `prescription`
  (templates + fpdf renderers + a `BASE_FIELDS` block each).
- Multi-page support (long letters, itemized invoices) — page-N PNGs + `page`
  key in ground truth.

### Phase 5 — Packaging for the win (1 day)
- **Pitch README** (`README.md` top section rewrite): the flywheel diagram,
  "what's inside" table, quickstart, the numbers table (docs/sec, exactness,
  offline-first), demo GIF.
- **Demo script** checked into `docs/` (the one above) + a 90-second video of
  the flywheel loop.
- **Metrics capture**: before submitting, run one full flywheel cycle and record
  CER/WER/field-accuracy deltas + wall-clock time; put the table in the README.
- `requirements.txt` pinning + CI (GitHub Actions: `pytest`, build frontend).

## 2.5 What to measure (the numbers that win)

| Metric | Where | Target for submission |
|---|---|---|
| Docs generated per run | manifest | 50 in < 60 s (offline, Faker path) |
| Ground-truth exactness | Phase 2 verifier | 100% of docs `verified: true` |
| Eval improvement per loop | Phase 3 regenerate | CER −20%+ or field-accuracy +10 pts after one targeted loop |
| Offline-first | demo | full run with no keys |
| Cost comparison | README | "≈$0 vs $2–5/doc for human labeling" |

## 2.6 Risks & mitigations

| Risk | Mitigation |
|---|---|
| "This is just NeMo branding on your own code" | Phase 1b integrates the **real** `data-designer` / `nemo-curator` / `safe-synthesizer` packages where they fit; the pitch names exact packages + APIs. The custom part (LaTeX/PDF/OCR ground truth) is precisely what NeMo doesn't provide. |
| Live web retrieval fails / slow at demo time | Default OFF with keys unset; cache results; demo script uses the LLM path only if the network is trusted, else offline Faker path. |
| fpdf2 fallback renders ugly | Phase 2 font fix + degradation pipeline makes "clean" renders a feature, not a bug. |
| Judge asks "why OCR?" | The eval loop is the point: without ground truth you can't measure, and this generates exact ground truth at scale. |
| Branch mess / demo breaks | Phase 0 first; freeze features after Phase 3; demo on a pinned commit. |

## 2.7 Final checklist (before submit)

- [ ] `main` has: merged wizard branch, wired QROTAID, font fix, verifier, regenerate + leaderboard
- [ ] Real integration: `data-designer` generation path runs with `NVIDIA_API_KEY`; Evaluator has run-compare + quality gate
- [ ] README stack diagram: custom core + which real NeMo packages at which phase (with Linux/GPU notes)
- [ ] `pytest` green (existing + new tests)
- [ ] Demo script rehearsed end-to-end, offline and online paths
- [ ] Numbers table filled from a real run in README
- [ ] 90-second video of the flywheel loop
- [ ] `.env` not committed; keys absent from repo
