# NeMo End-to-End Frontend App — Design Spec

**Date:** 2026-07-30  
**Status:** Approved for implementation planning  
**Repo:** `nv-sythsis-ocr-pdf` (Synthetic OCR PDF Studio)

## Summary

Upgrade the existing FastAPI synthetic OCR pipeline into a **full product UI**: a React + Vite wizard with one screen per NeMo stage — **Curator → Data Designer → Safe Synthesizer → NeMo Claw → Evaluator** — backed by hybrid APIs (one-shot pipeline + per-stage re-runs). NeMo Claw is an **in-app orchestrator chat** that can run/re-run stages and explain failures, with extension hooks for a future real NemoClaw/OpenShell integration.

## Goals

- Present the full NeMo-style story as a guided, stage-native workspace (not a single form + stage list).
- Let users pause, inspect, edit, and re-run individual stages without wiping the run.
- Give Claw real agency over the pipeline via tool-calling against stage APIs.
- Keep offline/Faker fallback and existing eval contracts working.
- Preserve NVIDIA-green visual language; evolve it into a React app.

## Non-goals (v1)

- Installing or requiring real NVIDIA NemoClaw / OpenShell sandboxes.
- Auth, multi-tenancy, or cloud deployment.
- Streaming SSE for long pipeline runs (polling is enough for v1).
- Replacing LaTeX/PDF generation with a separate stepper step (it remains a post-synthesize substep).

## Architecture

```
frontend/          React + Vite SPA (wizard + Claw rail)
app/               FastAPI (existing modules + stage APIs + Claw)
data/runs/<id>/    stage artifacts + manifest
```

```
Seed → Curator → Data Designer → Safe Synthesizer → (PDF/LaTeX) → Evaluator
                              ↕
                    NeMo Claw (side chat) can run/re-run any stage
```

- **Run all** keeps `POST /api/pipeline/run` (adapted to write stage files).
- Per-stage endpoints read/write the same run folder so Claw and the wizard share state.
- `POST /api/claw/chat` uses the existing LLM client + server-side tools; a `claw_provider` stub marks the future real-NemoClaw path.

## Wizard stages & screens

| Step | Job | Main UI | Artifacts |
|------|-----|---------|-----------|
| **1. Curator** | Seed + clean data | Source (empty / sample / HF), preview, curation report (dedup, filter, PII) | `seed.json`, `curated.json`, curator report |
| **2. Data Designer** | Shape dataset | Prompt, doc type, schema editor (fields, locale, currency, theme), design report | `schema.json` |
| **3. Safe Synthesizer** | Ground-truth JSON (+ PDF) | `num_docs`, seed, privacy toggles, record table, download JSON, PDF thumbs | `doc_*.{json,tex,pdf,png}`, synth/pdf reports |
| **4. Claw** | Orchestrate & recover | Chat + tool activity log; run all / re-run stage / explain / jump to Eval | `claw/messages.json` |
| **5. Evaluator** | Score OCR models | Pick run, model or upload predictions, metrics + per-doc diffs | eval records under `data/evals/` |

### Navigation rules

- Steps unlock in order once upstream artifacts exist (or after **Run all** fills them).
- Jumping back and re-running a stage marks downstream steps **stale** until re-run.
- PDF/LaTeX generation runs as a background substep after synthesize; thumbs appear on Synthesizer and Evaluator.

## Data model (run folder)

`data/runs/<run_id>/`:

```
manifest.json
seed.json
curated.json
schema.json
doc_{i}.json|.tex|.pdf|.png    # flat at run root (keeps Eval + /docs/{i}/{kind} working)
reports/{curator,designer,synthesizer,pdf}.json
claw/messages.json
```

`manifest.json` holds request snapshot, schema summary, stage statuses (`idle|running|done|error|stale`), timestamps, and `stage_error` when a stage fails.

**Compatibility:** Document artifacts stay flat `doc_{i}.*` at the run root so existing Eval and download routes need no path migration. New files are additive (`seed.json`, `curated.json`, `schema.json`, `reports/`, `claw/`).

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/runs` | Create empty run |
| `POST` | `/api/pipeline/run` | Run all (existing behavior, stage-file writes) |
| `POST` | `/api/runs/{id}/curate` | Seed + Curator |
| `POST` | `/api/runs/{id}/design` | Data Designer |
| `POST` | `/api/runs/{id}/synthesize` | Safe Synthesizer + LaTeX/PDF |
| `GET` | `/api/runs`, `/api/runs/{id}` | List / load manifest + stage summaries |
| `GET` | `/api/runs/{id}/docs/{i}/{kind}` | Existing artifact fetch |
| `POST` | `/api/claw/chat` | Claw message → tools → reply |
| `POST` | `/api/eval/run` | Existing eval |
| `GET` | `/api/evals`, `/api/evals/{id}` | Existing eval list/get |
| `GET` | `/api/health` | Existing health |

### Stage error shape

```json
{
  "ok": false,
  "stage": "designer",
  "error": "LLM timeout",
  "hint": "Retry design, or set NVIDIA_API_KEY for NIM; offline keyword design is available."
}
```

Successful stage responses return updated manifest (and stage-specific payload).

## NeMo Claw

**Role:** Orchestrator chat (not the LaTeX harness). Inspired in-app agent for v1.

**Tools (server-side):**

- `run_pipeline` — full run / continue
- `run_stage` — `curate` | `design` | `synthesize`
- `get_manifest` / `get_report`
- `list_docs`
- `suggest_fix` — grounded on `stage_error` + reports
- `start_eval` — kick eval or return deep-link payload for Evaluator step

**UX:** Right rail once a `run_id` exists; tool activity as compact chips; suggested prompts for common recovery paths.

**Future hook:** `claw_provider` interface with `InAppClawProvider` (default) and a stub `NemoClawProvider` documenting OpenShell integration (unimplemented).

## Frontend structure

```
frontend/
  src/
    App.tsx
    pages/          # Curator, Designer, Synthesizer, Claw, Evaluator
    components/     # StageReport, ArtifactViewer, DocGrid, MetricTiles, ClawRail
    api/client.ts
    state/runStore.ts
```

- Top stepper for five stages; main pane = current workspace; Claw rail on the right.
- Vite proxies `/api` → FastAPI.
- `run.ps1` / `run.sh` start backend (and optionally Vite) with `.env` loaded.
- Default UX is the React SPA. In production/dev-serve mode, FastAPI serves `frontend/dist` at `/` and keeps `/api/*`. The legacy `static/` site remains in-repo temporarily at `/legacy/` until removed after the React UI is verified.

## Branding & naming in UI

- **NeMo Curator**, **NeMo Data Designer**, **NeMo Safe Synthesizer**, **NeMo Claw**, **NeMo Evaluator**
- Product title can evolve to e.g. “NeMo Synthetic OCR Studio” while keeping the NVIDIA green accent (`#76B900`) and existing light/dark tokens.

## Error handling

- Stage failures persist on the run; UI banner on that step; Claw can read and suggest fixes.
- LLM timeouts: one retry, then clear offline / limited Claw messaging.
- Downstream **Stale** badges after upstream re-runs until those stages are re-executed.

## Testing

- Backend: stage endpoints + Claw tool routing with mocked LLM; extend existing error-surfacing tests.
- Frontend: smoke that stepper unlocks given mock artifacts.
- Manual: Run all → inspect stages → Claw re-run synthesize → Eval via uploaded predictions.

## Implementation order (high level)

1. Stage persistence + per-stage APIs (adapt `pipeline_run` and `storage`).
2. Claw chat endpoint + tools + provider stub.
3. React app scaffold, stepper, run store, API client.
4. Curator / Designer / Synthesizer pages wired to stage APIs.
5. Claw rail + Evaluator page (port Eval Lab).
6. Wire `run.ps1`/`run.sh` + README for dual-process (or static build serve).
7. Tests and polish (stale badges, offline hints).

## Decisions log

| Decision | Choice |
|----------|--------|
| Product shape | Wizard with dedicated stage screens |
| Claw role | Orchestrator chat |
| APIs | Hybrid: Run all + per-stage |
| Frontend | React + Vite; FastAPI backend |
| Real NemoClaw | Inspired now; hooks for later |
| Architecture style | Stage-native workspace (Approach 2) |
