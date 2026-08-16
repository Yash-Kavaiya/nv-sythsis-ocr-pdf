# Synthetic OCR PDF Studio

End-to-end website for generating **synthetic document datasets for OCR** and
**evaluating your own OCR model** against them — implementing this pipeline:

```
HuggingFace dataset / sample data / empty ──┐
                                            ▼
One prompt ──► NVIDIA synthetic data generation
               (Curator ► Data Designer ► Synthesizer)
                     │
                     ├──► JSON ground truth ─────────────┐
                     ├──► Agent harness → .tex templates │──► Eval UI: plug in your own
                     └──► PDF (+ page PNG) ──────────────┘    model, score OCR accuracy
                                                              via JSON + PDF structure
```

## Quickstart

**Recommended** — one command (installs Python deps, builds the React app if
needed, starts the API):

```bash
# Windows
.\run.ps1

# macOS / Linux
chmod +x run.sh && ./run.sh
```

Open **http://localhost:8000** for the **NeMo wizard** (React SPA). The
original single-page Studio and Eval Lab remain at **http://localhost:8000/legacy/**.

**Dual-process frontend dev** (hot reload via Vite, API on port 8000):

```bash
# Windows
$env:DEV_FRONTEND='1'; .\run.ps1

# macOS / Linux
DEV_FRONTEND=1 ./run.sh
```

Then open **http://localhost:5173** — Vite proxies `/api` to the backend.

<details>
<summary>or do it manually</summary>

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
</details>

## Wizard UI

The React app (`frontend/`) walks through five stages for each run:

| Step | Stage | What it does |
|------|-------|----------------|
| 1 | **NeMo Curator** | Load seed data (HuggingFace, sample corpus, or empty), run dedup/filter/normalize/PII scrub + web retrieval |
| 2 | **NeMo Data Designer** | Turn your prompt into a document schema (type, theme, fields, locale) |
| 3 | **NeMo Safe Synthesizer** | Generate N ground-truth JSON records + LaTeX/PDF/PNG artifacts |
| 4 | **NeMo Claw** | In-app orchestrator chat — ask what failed, re-run stages, inspect reports (optional; does not block Evaluator) |
| 5 | **NeMo Evaluator** | Score your OCR model (vision API or uploaded predictions) against ground truth |

Create a run from the header, then advance through the stepper. A **Claw rail**
appears on the side once a run exists (except on the full Claw page).

## Environment

The `run.ps1` / `run.sh` scripts source a gitignored `.env` if present, so you
can keep secrets in a file instead of exporting them each session:

```bash
echo 'NVIDIA_API_KEY=nvapi-...' > .env
```

Everything works fully offline without a key; optional upgrades:

| Env var | Effect |
|---|---|
| `NVIDIA_API_KEY` | Enables LLM-backed schema design, themed synthesis and LaTeX repair via [NVIDIA NIM](https://build.nvidia.com) (`integrate.api.nvidia.com`), and the real NeMo Data Designer engine. Without it, deterministic in-app engines run instead. |
| `NVIDIA_MODEL` / `NVIDIA_BASE_URL` | Override the default model (`nvidia/nemotron-3-ultra-550b-a55b`) or endpoint. |
| `OPENROUTER_API_KEY` / `SERP_API_KEY` | Optional: QROTAID web retrieval in the Curator (real-world document examples that ground schema design). Perplexity via OpenRouter first, Google SERP fallback. |
| `NEMO_CURATOR` | Set to `1` (Linux + `pip install nemo-curator`) to route seed curation through the real NeMo Curator pipeline instead of the in-app curator. |
| `DATA_DIR` | Where runs/evals are persisted (default `./data`). |
| `PORT` | API port for `run.ps1` / `run.sh` (default `8000`). |
| `DEV_FRONTEND` | Set to `1` to start Vite dev server alongside the API (see Quickstart). |

**Security:** Treat `NVIDIA_API_KEY` like a password. Do not paste keys into
issues, commits, or chat logs. Rotate the key at
[build.nvidia.com](https://build.nvidia.com) if it is ever exposed.

If `tectonic` or `pdflatex` is installed, PDFs are compiled from the generated
`.tex`; otherwise an equivalent pure-Python (fpdf2) renderer produces them.

## Real NeMo engines (provider architecture)

Every stage runs on an **in-app engine** (always available, offline) and can
switch to a **real NVIDIA NeMo package** when the environment supports it. The
engine for each stage is decided by `app/pipeline/providers.py` and shown in
`GET /api/health` under `nemo_providers`.

| Stage | In-app (default) | Real NeMo engine | When real is used |
|---|---|---|---|
| Curator | QROTAID: normalize, exact/near/semantic dedup, PII scrub, web retrieval | `nemo-curator` (GPU/Dask pipelines) | `NEMO_CURATOR=1` on Linux with the package installed |
| Data Designer | LLM schema design + keyword inference | `data-designer` (column orchestration) | `data-designer` installed **and** `NVIDIA_API_KEY` set |
| Safe Synthesizer | Faker/LLM generation with exact arithmetic | `data-designer` record generation (statistical samplers + LLM columns) | same as Data Designer; pick per-run with `generator` on `/synthesize` |
| Evaluator | CER/WER, field accuracy, structure F1 + **run compare, quality gates, paired-flip regression** (NeMo Evaluator concepts ported) | `nel` (Nemo Evaluator, install from source) | when `nel` is importable |

`POST /api/runs/{id}/synthesize` accepts `generator: "auto" | "inapp" | "nemo"`
(default `auto` = real NeMo Data Designer when available, else in-app). Real
engines never break a run: any failure falls back to the in-app engine with the
reason recorded in the stage report.

Optional installs live in [`requirements-optional.txt`](requirements-optional.txt)
and every supported variable is documented in [`.env.example`](.env.example).

## How it works

### Hybrid APIs

You can drive the pipeline two ways:

1. **Wizard (stage-by-stage)** — `POST /api/runs` then
   `POST /api/runs/{id}/curate`, `/design`, `/synthesize`. Each stage updates
   `manifest.json` with `stage_status` and persists artifacts under
   `data/runs/<run_id>/`.
2. **Run-all (legacy)** — `POST /api/pipeline/run` executes Curator → Designer →
   Synthesizer → LaTeX → PDF in one request (used by the legacy Studio UI).

**NeMo Claw** — `POST /api/claw/chat` with `{ run_id, message }` returns an
assistant reply plus optional tool calls (re-run synthesizer, show curator report,
etc.). Messages are persisted under `data/runs/<run_id>/claw/`.

### Studio — one prompt in, a dataset out (`POST /api/pipeline/run`)

1. **Seed** — rows from a HuggingFace dataset (via the datasets-server API),
   the bundled sample corpus, or nothing (prompt only).
2. **Curator** (QROTAID) — unicode/whitespace normalization, exact + near +
   semantic dedup, quality filter, PII scrub, plus optional web retrieval of
   real-world examples that ground the Designer; emits a per-stage report.
3. **Data Designer** — turns the prompt (+ seed stats) into a document schema:
   doc type (invoice / receipt / letter / form), theme, locale, currency, field
   list, item vocabulary. LLM-backed when a key is set, keyword inference otherwise.
4. **Synthesizer** — generates N ground-truth JSON records. Money fields are
   recomputed (`total = Σ items`, tax, …) so ground truth is arithmetically exact.
5. **LaTeX agent harness** — renders a Jinja2 `.tex` template per record
   (`app/latex/templates/`), validates it (brace balance, env pairing,
   unresolved vars), and asks the LLM to repair invalid output when available.
6. **PDF** — compiles the `.tex` (tectonic/pdflatex) or renders an equivalent
   layout with fpdf2, then rasterizes page 1 to PNG for vision models.

Each run persists `doc_i.json` / `doc_i.tex` / `doc_i.pdf` / `doc_i.png` plus a
manifest under `data/runs/<run_id>/`, all downloadable from the UI or API.

### Eval Lab — bring your own model (`POST /api/eval/run`)

Two ways to get predictions:

- **Call my model** — point at any OpenAI-compatible vision endpoint (NVIDIA
  NIM, OpenAI, vLLM, Ollama…). Each document's page image is sent with a
  JSON-extraction prompt; the reply is parsed as the predicted JSON.
- **Upload predictions** — paste `{"0": {...}, "1": {...}}` keyed by doc index
  (run your OCR offline, evaluate here).

Scoring against the ground-truth JSON:

| Metric | Meaning |
|---|---|
| Field accuracy | exact matches over flattened JSON paths (money/text normalized) |
| Fuzzy accuracy | mean per-field similarity (1 − normalized edit distance) |
| CER / WER | character/word error rate over the document's reading-order text |
| Structure F1 | precision/recall of the predicted JSON key tree vs ground truth |

Results show as stat tiles, a per-document accuracy chart, and an expandable
field-level diff table; evals are persisted and comparable across models.
Beyond raw scores, the Evaluator ports the rigor of NeMo Evaluator (`nel`):
**run comparison** with per-metric deltas and a paired sign test
(`POST /api/evals/compare`), **quality gates** (GO / NO-GO from thresholds,
`POST /api/evals/{id}/gate`), and a **model leaderboard**
(`GET /api/leaderboard`) — so "the model (or dataset) improved" is a tested
claim, not a vibe.

## API surface

```
GET  /api/health                             LLM + LaTeX engine status
GET  /api/hf/preview?dataset=…               preview HuggingFace rows
GET  /api/sample/preview                     preview bundled sample corpus
POST /api/runs                               create run (wizard entry)
POST /api/runs/{id}/curate                   run Curator stage
POST /api/runs/{id}/design                   run Data Designer stage
POST /api/runs/{id}/synthesize               run Synthesizer stage
POST /api/claw/chat                          NeMo Claw orchestrator chat
POST /api/pipeline/run                       run the full generation pipeline
GET  /api/runs                               list runs
GET  /api/runs/{id}                          run manifest (stages, schema, docs)
GET  /api/runs/{id}/dataset                  download all ground-truth JSON
GET  /api/runs/{id}/docs/{i}/{json|tex|pdf|png}
POST /api/eval/run                           evaluate a model or uploaded predictions
GET  /api/evals · /api/evals/{id}            list / fetch eval results
GET  /api/leaderboard                        rank models by fuzzy field accuracy
POST /api/evals/compare                      nel-style run comparison + paired sign test
POST /api/evals/{id}/gate                    GO / NO-GO quality gate from thresholds
```

## Project layout

```
app/
  main.py               FastAPI app + API routes; serves SPA or legacy static
  models.py             request/response schemas
  storage.py            run & eval persistence (filesystem)
  pipeline/
    stages.py           per-stage runners + manifest status helpers
    providers.py        engine resolution per stage (in-app vs real NeMo)
    data_designer_provider.py  real NeMo Data Designer record generation
    nemo_curator_provider.py   real NeMo Curator seed curation (gated)
    safe_synthesizer_provider.py  privacy report + DP upgrade tier (gated)
    hf_loader.py        HuggingFace datasets-server + sample corpus loading
    curator.py          QROTAID: dedup / filter / normalize / PII scrub / web retrieval
    designer.py         prompt → document schema
    synthesizer.py      schema → ground-truth JSON records
    llm.py              OpenAI-compatible client (NVIDIA NIM)
  claw/                 NeMo Claw chat + tool execution
  latex/
    harness.py          JSON → .tex agent loop (render, validate, repair)
    templates/          invoice / receipt / letter / form Jinja2 LaTeX templates
  pdfgen/
    compiler.py         tectonic/pdflatex compile + PNG rasterization
    fpdf_renderer.py    pure-Python PDF fallback renderer
  evals/
    metrics.py          CER, WER, field accuracy, structure F1
    runner.py           vision-model calls + scoring
frontend/               React + Vite wizard (build → dist/, served at /)
static/                 legacy website (Studio + Eval Lab, served at /legacy/)
run.ps1 / run.sh        one-command start scripts
```
