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

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000> — **Studio** (generate documents) and
<http://localhost:8000/eval.html> — **Eval Lab** (score an OCR model).

Everything works fully offline out of the box. Two optional upgrades:

| Env var | Effect |
|---|---|
| `NVIDIA_API_KEY` | Enables LLM-backed schema design, themed synthesis and LaTeX repair via [NVIDIA NIM](https://build.nvidia.com) (`integrate.api.nvidia.com`). Without it, a deterministic Faker-based synthesizer runs instead. |
| `NVIDIA_MODEL` / `NVIDIA_BASE_URL` | Override the default model (`meta/llama-3.1-70b-instruct`) or endpoint. |
| `DATA_DIR` | Where runs/evals are persisted (default `./data`). |

If `tectonic` or `pdflatex` is installed, PDFs are compiled from the generated
`.tex`; otherwise an equivalent pure-Python (fpdf2) renderer produces them.

## How it works

### Studio — one prompt in, a dataset out (`POST /api/pipeline/run`)

1. **Seed** — rows from a HuggingFace dataset (via the datasets-server API),
   the bundled sample corpus, or nothing (prompt only).
2. **Curator** (NeMo-Curator-style) — unicode/whitespace normalization, exact +
   near dedup, quality filter, PII scrub; emits a per-stage report.
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

## API surface

```
GET  /api/health                             LLM + LaTeX engine status
GET  /api/hf/preview?dataset=…               preview HuggingFace rows
GET  /api/sample/preview                     preview bundled sample corpus
POST /api/pipeline/run                       run the full generation pipeline
GET  /api/runs                               list runs
GET  /api/runs/{id}                          run manifest (stages, schema, docs)
GET  /api/runs/{id}/dataset                  download all ground-truth JSON
GET  /api/runs/{id}/docs/{i}/{json|tex|pdf|png}
POST /api/eval/run                           evaluate a model or uploaded predictions
GET  /api/evals · /api/evals/{id}            list / fetch eval results
```

## Project layout

```
app/
  main.py               FastAPI app + API routes, serves the static site
  models.py             request/response schemas
  storage.py            run & eval persistence (filesystem)
  pipeline/
    hf_loader.py        HuggingFace datasets-server + sample corpus loading
    curator.py          dedup / filter / normalize / PII scrub
    designer.py         prompt → document schema
    synthesizer.py      schema → ground-truth JSON records
    llm.py              OpenAI-compatible client (NVIDIA NIM)
  latex/
    harness.py          JSON → .tex agent loop (render, validate, repair)
    templates/          invoice / receipt / letter / form Jinja2 LaTeX templates
  pdfgen/
    compiler.py         tectonic/pdflatex compile + PNG rasterization
    fpdf_renderer.py    pure-Python PDF fallback renderer
  evals/
    metrics.py          CER, WER, field accuracy, structure F1
    runner.py           vision-model calls + scoring
static/                 the website (Studio + Eval Lab, no build step)
```
