# NeMo E2E Frontend Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a React + Vite wizard (Curator → Data Designer → Safe Synthesizer → NeMo Claw → Evaluator) on the existing FastAPI OCR pipeline, with hybrid stage APIs and an in-app Claw orchestrator.

**Architecture:** Extract stage services that read/write `data/runs/<id>/` (flat `doc_*` artifacts + additive `seed.json` / `curated.json` / `schema.json` / `reports/` / `claw/`). Keep `POST /api/pipeline/run` as Run-all. Add `POST /api/claw/chat` with tool-calling. Serve `frontend/dist` from FastAPI; Vite proxies `/api` in dev.

**Tech Stack:** FastAPI, Pydantic v2, existing pipeline modules, React 18 + Vite + TypeScript, CSS variables from current NVIDIA-green tokens, pytest + httpx TestClient, Vitest optional smoke only if time allows.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-nemo-e2e-frontend-design.md`
- Document artifacts stay flat: `doc_{i}.json|.tex|.pdf|.png` at run root (Eval paths unchanged)
- No real OpenShell/NemoClaw install in v1 — `NemoClawProvider` stub only
- No auth / multi-user / SSE streaming in v1
- Do not commit `.env` or API keys
- Product stage names in UI: NeMo Curator, NeMo Data Designer, NeMo Safe Synthesizer, NeMo Claw, NeMo Evaluator
- Accent color `#76B900`; prefer existing light/dark token approach
- Commits after each task; never skip hooks

## File map

| Path | Responsibility |
|------|----------------|
| `app/pipeline/stages.py` | Stage runners: create_run, curate, design, synthesize; manifest stage status helpers |
| `app/claw/provider.py` | `ClawProvider` protocol, `InAppClawProvider`, stub `NemoClawProvider` |
| `app/claw/tools.py` | Tool registry + execute(tool_name, args, run_id) |
| `app/claw/chat.py` | Chat loop: LLM + tools → reply + message persist |
| `app/models.py` | Add CurateRequest, DesignRequest, SynthesizeRequest, ClawChatRequest, StageError |
| `app/storage.py` | Helpers: write_json/read_json under run, save/load claw messages, mark_stale |
| `app/main.py` | Wire new routes; serve `frontend/dist` at `/`, legacy static at `/legacy` |
| `tests/test_stages.py` | Stage API + persistence tests |
| `tests/test_claw.py` | Claw tools + chat (mocked LLM) |
| `frontend/` | Vite React TS app |
| `frontend/src/state/runStore.ts` | Current run_id, step, stage statuses |
| `frontend/src/api/client.ts` | Typed fetch wrappers |
| `frontend/src/pages/*` | Five stage pages |
| `frontend/src/components/ClawRail.tsx` | Side chat |
| `run.ps1` / `run.sh` | Start API (+ optional Vite) |
| `README.md` | Document wizard + dual-process / build |

---

### Task 1: Stage persistence helpers + create run

**Files:**
- Create: `app/pipeline/stages.py`
- Modify: `app/storage.py`
- Modify: `app/models.py`
- Test: `tests/test_stages.py`

**Interfaces:**
- Produces:
  - `storage.write_run_json(run_id: str, relative: str, data: Any) -> None`
  - `storage.read_run_json(run_id: str, relative: str) -> Any`
  - `storage.mark_downstream_stale(manifest: dict, from_stage: str) -> dict`
  - `stages.STAGE_ORDER = ["curator", "designer", "synthesizer", "claw", "evaluator"]`
  - `stages.empty_manifest(run_id: str, request: dict | None = None) -> dict`
  - `stages.set_stage_status(manifest: dict, stage: str, status: str, detail: dict | None = None, error: str | None = None) -> dict`
  - `stages.create_run(prompt: str = "", source_type: str = "empty") -> dict`  # creates dir + manifest

- [ ] **Step 1: Write the failing test**

```python
# tests/test_stages.py
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Point DATA_DIR at tmp before importing app
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Re-import storage paths if module already cached — prefer patching app.storage.DATA_DIR
    import app.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(storage, "EVALS_DIR", tmp_path / "evals")
    from app.main import app
    return TestClient(app)


def test_create_run_writes_manifest(client, tmp_path):
    r = client.post("/api/runs", json={"prompt": "pharmacy invoices", "source_type": "empty"})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"].startswith("run_")
    assert (tmp_path / "runs" / body["run_id"] / "manifest.json").exists()
    assert body["stage_status"]["curator"] == "idle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stages.py::test_create_run_writes_manifest -v`  
Expected: FAIL (404 or missing route / import)

- [ ] **Step 3: Implement storage helpers + empty manifest + POST /api/runs**

In `app/storage.py` add `write_run_json` / `read_run_json` (path-safe under `run_dir`).  
In `app/pipeline/stages.py` implement `empty_manifest`, `set_stage_status`, `mark_downstream_stale` (when `from_stage` is curator → mark designer/synthesizer stale; designer → synthesizer; synthesizer → none for docs regen handled separately), `create_run`.  
In `app/models.py` add:

```python
class CreateRunRequest(BaseModel):
    prompt: str = ""
    source_type: SourceType = "empty"
    hf_dataset: Optional[str] = None
    hf_config: Optional[str] = None
    hf_split: str = "train"


class StageErrorBody(BaseModel):
    ok: bool = False
    stage: str
    error: str
    hint: str = ""
```

Manifest shape for v1 (extend existing keys, keep backward compatible):

```python
{
  "run_id": "...",
  "created_at": "...",
  "request": {...},
  "schema": {},
  "stages": [],          # keep list reports for UI parity
  "stage_status": {      # NEW
    "curator": "idle",
    "designer": "idle",
    "synthesizer": "idle",
    "claw": "idle",
    "evaluator": "idle",
  },
  "stage_error": None,   # {"stage","error","hint"} or null
  "docs": [],
  "llm_backed": False,
}
```

Wire `POST /api/runs` in `main.py` calling `stages.create_run`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stages.py::test_create_run_writes_manifest -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/storage.py app/pipeline/stages.py app/models.py app/main.py tests/test_stages.py
git commit -m "feat: add run creation and stage status helpers"
```

---

### Task 2: Curate stage API

**Files:**
- Modify: `app/pipeline/stages.py`
- Modify: `app/models.py`
- Modify: `app/main.py`
- Test: `tests/test_stages.py`

**Interfaces:**
- Consumes: `stages.create_run`, curator + hf_loader
- Produces: `stages.run_curate(run_id: str, req: CurateRequest) -> dict`  
  Writes `seed.json`, `curated.json`, `reports/curator.json`; updates manifest; marks designer/synthesizer stale if they were done

```python
class CurateRequest(BaseModel):
    source_type: SourceType = "empty"
    hf_dataset: Optional[str] = None
    hf_config: Optional[str] = None
    hf_split: str = "train"
```

- [ ] **Step 1: Write the failing test**

```python
def test_curate_sample_writes_curated(client, tmp_path):
    run_id = client.post("/api/runs", json={"prompt": "x", "source_type": "sample"}).json()["run_id"]
    r = client.post(f"/api/runs/{run_id}/curate", json={"source_type": "sample"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["manifest"]["stage_status"]["curator"] == "done"
    curated = (tmp_path / "runs" / run_id / "curated.json").read_text()
    assert len(curated) > 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_stages.py::test_curate_sample_writes_curated -v`  
Expected: FAIL (404)

- [ ] **Step 3: Implement `run_curate` + route**

Logic mirrors `pipeline_run` seed + curator block: load seed → `curator.curate` → write files → append stages report → set status done. On exception return 200 with `{ok:false, stage, error, hint}` OR raise HTTPException — prefer JSON body `{ok:false,...}` with HTTP 200 for Claw-friendly handling **or** HTTP 422/502 with `StageErrorBody`; pick **HTTP 400/502 + StageErrorBody** and also persist `stage_error` on manifest.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_stages.py::test_curate_sample_writes_curated -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/stages.py app/models.py app/main.py tests/test_stages.py
git commit -m "feat: add NeMo Curator stage API"
```

---

### Task 3: Design stage API

**Files:**
- Modify: `app/pipeline/stages.py`, `app/models.py`, `app/main.py`
- Test: `tests/test_stages.py`

**Interfaces:**
- Produces: `stages.run_design(run_id: str, prompt: str, doc_type: str | None, llm: LLMClient) -> dict`  
  Requires `curated.json` (or empty list if curator done with empty seed). Writes `schema.json`, `reports/designer.json`.

```python
class DesignRequest(BaseModel):
    prompt: str = Field(..., min_length=3)
    doc_type: Optional[DocType] = None
```

- [ ] **Step 1: Write failing test**

```python
def test_design_requires_curator(client):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    r = client.post(f"/api/runs/{run_id}/design", json={"prompt": "pharmacy invoices INR"})
    assert r.status_code in (400, 409)


def test_design_after_curate(client, tmp_path):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    r = client.post(f"/api/runs/{run_id}/design", json={"prompt": "pharmacy invoices in rupees"})
    assert r.status_code == 200
    assert r.json()["manifest"]["stage_status"]["designer"] == "done"
    assert (tmp_path / "runs" / run_id / "schema.json").exists()
```

- [ ] **Step 2: Run tests — expect fail**

Run: `pytest tests/test_stages.py::test_design_requires_curator tests/test_stages.py::test_design_after_curate -v`

- [ ] **Step 3: Implement `run_design` + `POST /api/runs/{id}/design`**

Use `designer.design_schema` + `curator.seed_stats`. Mark synthesizer stale if previously done.

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add NeMo Data Designer stage API"
```

---

### Task 4: Synthesize stage API (+ PDF)

**Files:**
- Modify: `app/pipeline/stages.py`, `app/models.py`, `app/main.py`
- Test: `tests/test_stages.py`

**Interfaces:**
- Produces: `stages.run_synthesize(run_id: str, num_docs: int, seed: int | None, llm: LLMClient, privacy_safe: bool = True) -> dict`  
  Requires `schema.json`. Writes `doc_i.*`, `reports/synthesizer.json`, `reports/pdf.json`. Updates `docs` on manifest.

```python
class SynthesizeRequest(BaseModel):
    num_docs: int = Field(5, ge=1, le=50)
    seed: Optional[int] = None
    privacy_safe: bool = True  # when True, keep PII scrubbing labels in theme notes / report flag
```

- [ ] **Step 1: Write failing test**

```python
def test_synthesize_after_design(client, tmp_path):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    client.post(f"/api/runs/{run_id}/design", json={"prompt": "simple retail invoices USD"})
    r = client.post(f"/api/runs/{run_id}/synthesize", json={"num_docs": 2, "seed": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["stage_status"]["synthesizer"] == "done"
    assert len(body["manifest"]["docs"]) == 2
    assert (tmp_path / "runs" / run_id / "doc_0.json").exists()
    assert (tmp_path / "runs" / run_id / "doc_0.pdf").exists()
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement by extracting LaTeX/PDF loop from `pipeline_run` into `run_synthesize`**

Reuse `synthesizer.synthesize`, `generate_tex`, `create_pdf`, `pdf_to_png`. Set `reports/synthesizer.json` detail to include `privacy_safe`.

- [ ] **Step 4: Run — expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add NeMo Safe Synthesizer stage API"
```

---

### Task 5: Refactor Run-all to call stage services

**Files:**
- Modify: `app/main.py` (`pipeline_run`)
- Modify: `app/pipeline/stages.py` (`run_pipeline_all`)
- Test: `tests/test_stages.py`

**Interfaces:**
- Produces: `stages.run_pipeline_all(req: PipelineRequest, llm: LLMClient) -> dict`  
  create_run → curate → design → synthesize; return full manifest (same shape as today plus `stage_status`)

- [ ] **Step 1: Write failing test**

```python
def test_pipeline_run_still_works(client, tmp_path):
    r = client.post("/api/pipeline/run", json={
        "source_type": "empty",
        "prompt": "short test invoices",
        "num_docs": 1,
        "seed": 42,
    })
    assert r.status_code == 200
    m = r.json()
    assert m["docs"]
    assert m["stage_status"]["synthesizer"] == "done"
    assert (tmp_path / "runs" / m["run_id"] / "schema.json").exists()
```

- [ ] **Step 2: Run — expect fail or partial (missing stage_status)**

- [ ] **Step 3: Replace body of `pipeline_run` with `return stages.run_pipeline_all(req, LLMClient())`**

Keep response keys: `run_id`, `created_at`, `request`, `schema`, `stages`, `docs`, `llm_backed`, plus `stage_status`.

- [ ] **Step 4: Run — expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor: Run-all pipeline uses stage services"
```

---

### Task 6: Claw tools + chat API

**Files:**
- Create: `app/claw/__init__.py`, `app/claw/provider.py`, `app/claw/tools.py`, `app/claw/chat.py`
- Modify: `app/models.py`, `app/main.py`, `app/storage.py`
- Test: `tests/test_claw.py`

**Interfaces:**
- Produces:
  - `ClawProvider.chat(run_id: str, message: str, history: list[dict]) -> dict` with keys `reply`, `tool_calls`, `messages`
  - Tools: `run_pipeline`, `run_stage`, `get_manifest`, `get_report`, `list_docs`, `suggest_fix`, `start_eval`
  - `POST /api/claw/chat` body: `{run_id, message}` → `{reply, tool_calls, messages}`
  - Persist history to `claw/messages.json`

```python
class ClawChatRequest(BaseModel):
    run_id: str
    message: str = Field(..., min_length=1)
```

- [ ] **Step 1: Write failing tests**

```python
# tests/test_claw.py
def test_get_manifest_tool(client):
    run_id = client.post("/api/runs", json={"prompt": "x"}).json()["run_id"]
    from app.claw.tools import execute_tool
    out = execute_tool("get_manifest", {}, run_id)
    assert out["run_id"] == run_id


def test_claw_chat_offline_no_crash(client, monkeypatch):
    # Force LLM unavailable
    import app.pipeline.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMClient, "available", property(lambda self: False))
    run_id = client.post("/api/runs", json={"prompt": "x"}).json()["run_id"]
    r = client.post("/api/claw/chat", json={"run_id": run_id, "message": "What stages are done?"})
    assert r.status_code == 200
    assert "reply" in r.json()
```

For offline path: `InAppClawProvider` without LLM should still run heuristic tool selection (e.g. if message contains "manifest" → get_manifest) or return a fixed help reply listing tools.

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement**

`provider.py`:
```python
class ClawProvider(Protocol):
    def chat(self, run_id: str, message: str, history: list[dict]) -> dict: ...

class InAppClawProvider:
    def chat(...): ...  # LLM with tool schema if available; else heuristic

class NemoClawProvider:
    def chat(...):
        raise NotImplementedError(
            "Real NemoClaw/OpenShell is not wired in v1. Use InAppClawProvider."
        )
```

When LLM available: send system prompt describing tools + JSON tool-call protocol (simple: model returns `{"tool":"...","args":{...}}` or plain text). Execute tool, append observation, ask for final reply (max 2 tool rounds).

- [ ] **Step 4: Run — expect pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: add in-app NeMo Claw chat and tools"
```

---

### Task 7: React + Vite scaffold

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/styles.css` (port tokens from `static/css/style.css`)

**Interfaces:**
- Vite proxy: `/api` → `http://127.0.0.1:8000`
- App renders shell: header (logo “NeMo Synthetic OCR Studio”), stepper placeholders, empty main

- [ ] **Step 1: Scaffold**

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
```

If directory non-empty, create files manually with Vite React-TS defaults.

`vite.config.ts`:
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
```

- [ ] **Step 2: Port CSS variables** from `static/css/style.css` into `frontend/src/styles.css` (keep accent `#76B900`, light/dark `data-theme`)

- [ ] **Step 3: Minimal App**

```tsx
const STEPS = [
  "Curator",
  "Data Designer",
  "Safe Synthesizer",
  "Claw",
  "Evaluator",
] as const;
```

Render stepper + “Create run” button calling `POST /api/runs` (inline fetch ok for now).

- [ ] **Step 4: Verify**

Run backend: `.\run.ps1` (separate terminal)  
Run: `cd frontend; npm run dev`  
Open http://localhost:5173 — shell loads; Create run returns id.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: scaffold React Vite NeMo studio frontend"
```

Add `frontend/node_modules/` to `.gitignore` if not already covered by root `node_modules/`.

---

### Task 8: API client + run store + stepper unlock logic

**Files:**
- Create: `frontend/src/api/client.ts`, `frontend/src/state/runStore.ts`, `frontend/src/components/Stepper.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
```ts
// client.ts
export type Manifest = {
  run_id: string;
  stage_status: Record<string, string>;
  stage_error?: { stage: string; error: string; hint: string } | null;
  schema?: Record<string, unknown>;
  docs?: Array<Record<string, unknown>>;
  stages?: Array<{ stage: string; detail: Record<string, unknown> }>;
  request?: Record<string, unknown>;
  llm_backed?: boolean;
};

export async function createRun(body: object): Promise<Manifest>;
export async function curate(runId: string, body: object): Promise<{ ok: boolean; manifest: Manifest }>;
export async function design(runId: string, body: object): Promise<{ ok: boolean; manifest: Manifest }>;
export async function synthesize(runId: string, body: object): Promise<{ ok: boolean; manifest: Manifest }>;
export async function runPipeline(body: object): Promise<Manifest>;
export async function clawChat(runId: string, message: string): Promise<{ reply: string; tool_calls: unknown[]; messages: unknown[] }>;
export async function getRun(runId: string): Promise<Manifest>;
export async function listRuns(): Promise<unknown[]>;
export async function runEval(body: object): Promise<unknown>;
export async function health(): Promise<unknown>;
```

Unlock rule: step index `i` enabled if all stages before it are `done` **or** `stale` (stale still allows viewing), except first step always enabled when `run_id` exists. Without `run_id`, only step 0 for creating/curating.

- [ ] **Step 1: Implement client + store (useState/context is enough — no Redux)**

```tsx
// runStore.tsx
type RunState = {
  runId: string | null;
  manifest: Manifest | null;
  step: number;
  setStep: (n: number) => void;
  refresh: () => Promise<void>;
  setManifest: (m: Manifest) => void;
};
```

- [ ] **Step 2: Wire Stepper into App**

- [ ] **Step 3: Manual check** — create run, step buttons respect lock

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add API client, run store, and stepper unlock rules"
```

---

### Task 9: Curator page

**Files:**
- Create: `frontend/src/pages/CuratorPage.tsx`, `frontend/src/components/StageReport.tsx`
- Modify: `App.tsx`

- [ ] **Step 1: Build UI** — source radios, HF fields + preview (`GET /api/hf/preview`, `GET /api/sample/preview`), Run Curator button, report panel, Run all shortcut (`runPipeline`)

- [ ] **Step 2: On success** `setManifest`, advance to step 1 optional

- [ ] **Step 3: Manual test** with sample source

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add NeMo Curator wizard page"
```

---

### Task 10: Data Designer page

**Files:**
- Create: `frontend/src/pages/DesignerPage.tsx`
- Modify: `App.tsx`

- [ ] **Step 1: UI** — prompt textarea, doc type select, Run Designer, JSON schema view/edit (textarea editable → save by re-posting design or `PUT` optional; v1: edit local then “Re-run design” with same prompt is enough; if user edits schema JSON, write via new optional endpoint OR skip write-back in v1 and only display)

**v1 decision (explicit):** schema is display + re-run design only; no raw schema PUT.

- [ ] **Step 2: Manual test** after curator

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: add NeMo Data Designer wizard page"
```

---

### Task 11: Safe Synthesizer page

**Files:**
- Create: `frontend/src/pages/SynthesizerPage.tsx`, `frontend/src/components/DocGrid.tsx`
- Modify: `App.tsx`

- [ ] **Step 1: UI** — num_docs, seed, privacy_safe checkbox, Run Synthesize, DocGrid (png thumb, JSON/PDF links using existing `/api/runs/{id}/docs/{i}/{kind}`), download dataset link

- [ ] **Step 2: Show stale banner if `stage_status.synthesizer === "stale"`

- [ ] **Step 3: Manual test** — 2 docs offline

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add NeMo Safe Synthesizer wizard page"
```

---

### Task 12: Claw rail + Claw page

**Files:**
- Create: `frontend/src/components/ClawRail.tsx`, `frontend/src/pages/ClawPage.tsx`
- Modify: `App.tsx`

- [ ] **Step 1: ClawRail** — message list, input, suggested chips (“What failed?”, “Re-run synthesizer”, “Show curator report”), tool_call chips under assistant messages

- [ ] **Step 2: Show rail when `runId` set (all steps); Claw page is enlarged chat + activity log

- [ ] **Step 3: Manual test** offline help reply + with key if available

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add NeMo Claw chat rail and page"
```

---

### Task 13: Evaluator page

**Files:**
- Create: `frontend/src/pages/EvaluatorPage.tsx`, `frontend/src/components/MetricTiles.tsx`
- Modify: `App.tsx`
- Reference: port behavior from `static/eval.html` + `static/js/eval.js`

- [ ] **Step 1: Port eval form** — run select (current run default), mode model/upload, provider fields, Run Eval, tiles + per-doc table

- [ ] **Step 2: Call `POST /api/eval/run` unchanged

- [ ] **Step 3: Manual test** with upload predictions against a 1-doc run

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add NeMo Evaluator wizard page"
```

---

### Task 14: Serve SPA from FastAPI + scripts + README

**Files:**
- Modify: `app/main.py`, `run.ps1`, `run.sh`, `README.md`, `.gitignore`

- [ ] **Step 1: Build frontend**

```bash
cd frontend && npm run build
```

- [ ] **Step 2: Mount in FastAPI**

```python
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
LEGACY_STATIC = Path(__file__).resolve().parent.parent / "static"

# API routes first...
if FRONTEND_DIST.exists():
    app.mount("/legacy", StaticFiles(directory=str(LEGACY_STATIC), html=True), name="legacy")
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="spa")
else:
    app.mount("/", StaticFiles(directory=str(LEGACY_STATIC), html=True), name="static")
```

Ensure API routes are registered **before** the `/` mount (already true).

- [ ] **Step 3: Update `run.ps1` / `run.sh`**

- Load `.env` (already)
- `pip install`
- If `$env:DEV_FRONTEND -eq '1'`: print Vite instructions or start `npm run dev` as background job
- Default: `npm run build` when `frontend/package.json` exists and dist missing (optional; or document manual build)
- Print URLs: Studio http://localhost:PORT (SPA), Legacy /legacy/

- [ ] **Step 4: Update README** — wizard stages, Claw, hybrid APIs, env key, rotate-key note (do not paste secrets)

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: serve React SPA from FastAPI and update run scripts"
```

---

### Task 15: Integration polish + regression tests

**Files:**
- Modify: `tests/test_stages.py`, `tests/test_claw.py`
- Fix: any stale-badge / error-banner gaps in frontend

- [ ] **Step 1: Add test** re-curate marks designer stale

```python
def test_recurate_marks_designer_stale(client):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    client.post(f"/api/runs/{run_id}/design", json={"prompt": "pharmacy invoices rupees"})
    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    m = client.get(f"/api/runs/{run_id}").json()
    assert m["stage_status"]["designer"] == "stale"
```

- [ ] **Step 2: Run full suite**

```bash
pytest -v
```

Expected: all pass (including `test_error_surfacing.py`)

- [ ] **Step 3: Manual E2E** — Run all from UI → inspect stages → Claw “re-run synthesizer” → Eval upload

- [ ] **Step 4: Commit**

```bash
git commit -m "test: cover stale stages and Claw offline path"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Wizard 5 stages | 7–13 |
| Hybrid APIs + Run all | 1–5 |
| Flat doc_* artifacts | 4–5 |
| Claw orchestrator + tools | 6, 12 |
| NemoClaw stub hook | 6 |
| Evaluator port | 13 |
| SPA default + /legacy | 14 |
| Stale downstream | 2–3, 15 |
| Offline / no key | 4, 6 |
| NVIDIA green branding | 7 |

## Placeholder / consistency self-review

- No TBD steps left; schema PUT explicitly deferred.
- Tool names consistent: `run_pipeline`, `run_stage`, `get_manifest`, `get_report`, `list_docs`, `suggest_fix`, `start_eval`.
- Manifest always includes `stage_status` after Task 1+.
- Stage HTTP paths match spec: `/api/runs/{id}/curate|design|synthesize`, `/api/claw/chat`.
