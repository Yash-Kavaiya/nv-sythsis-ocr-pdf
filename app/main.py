"""NVIDIA-style synthetic OCR document pipeline - FastAPI app.

Flow (mirrors the architecture diagram):
  seed source (HuggingFace / sample / empty) + one prompt
    -> Curator -> Data Designer -> Synthesizer     (synthetic data generation)
    -> JSON ground truth -> LaTeX agent harness -> PDF
    -> separate Eval UI: plug in your own OCR model, score accuracy vs JSON + structure.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import storage
from .evals import rigor
from .evals.metrics import aggregate
from .evals.runner import resolve_model_config, run_eval
from .claw.chat import handle_claw_chat
from .models import (
    ClawChatRequest,
    CompareEvalsRequest,
    CreateRunRequest,
    CurateRequest,
    DesignRequest,
    EvalRequest,
    PipelineRequest,
    QualityGateRequest,
    StageErrorBody,
    SynthesizeRequest,
)
from .pipeline import providers, stages
from .pdfgen.compiler import find_latex_engine
from .pipeline import hf_loader
from .pipeline.llm import LLMClient

app = FastAPI(title="NV Synthetic OCR PDF Studio", version="1.0.0")
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
LEGACY_STATIC = Path(__file__).resolve().parent.parent / "static"


# ---------------------------------------------------------------- health

@app.get("/api/health")
def health():
    llm = LLMClient()
    engine = find_latex_engine()
    return {
        "status": "ok",
        "llm_available": llm.available,
        "llm_model": llm.model if llm.available else None,
        "latex_engine": engine[0] if engine else "fpdf2 fallback",
        "nemo_providers": providers.status(),
    }


# ---------------------------------------------------------------- seed preview

@app.get("/api/hf/preview")
def hf_preview(dataset: str, config: str | None = None, split: str = "train", limit: int = 5):
    try:
        rows = hf_loader.load_hf_rows(dataset, config, split, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load dataset: {exc}")
    return {"dataset": dataset, "rows": rows[:limit], "count": len(rows)}


@app.get("/api/sample/preview")
def sample_preview():
    rows = hf_loader.load_sample_seed()
    return {"rows": rows[:5], "count": len(rows)}


# ---------------------------------------------------------------- pipeline

@app.post("/api/pipeline/run")
def pipeline_run(req: PipelineRequest):
    try:
        return stages.run_pipeline_all(req, LLMClient())
    except stages.StageFailure as exc:
        body = StageErrorBody(stage=exc.stage, error=exc.error, hint=exc.hint)
        return JSONResponse(status_code=exc.http_status, content=body.model_dump())


# ---------------------------------------------------------------- runs & artifacts

@app.post("/api/runs")
def runs_create(req: CreateRunRequest):
    manifest = stages.create_run(req.prompt, req.source_type)
    manifest["request"] = req.model_dump()
    storage.save_manifest(manifest)
    return manifest


@app.post("/api/runs/{run_id}/curate")
def runs_curate(run_id: str, req: CurateRequest):
    try:
        return stages.run_curate(run_id, req)
    except stages.RunNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    except stages.StageFailure as exc:
        body = StageErrorBody(stage=exc.stage, error=exc.error, hint=exc.hint)
        return JSONResponse(status_code=exc.http_status, content=body.model_dump())


@app.post("/api/runs/{run_id}/design")
def runs_design(run_id: str, req: DesignRequest):
    llm = LLMClient()
    try:
        return stages.run_design(run_id, req.prompt, req.doc_type, llm)
    except stages.RunNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    except stages.StageFailure as exc:
        body = StageErrorBody(stage=exc.stage, error=exc.error, hint=exc.hint)
        return JSONResponse(status_code=exc.http_status, content=body.model_dump())


@app.post("/api/runs/{run_id}/synthesize")
def runs_synthesize(run_id: str, req: SynthesizeRequest):
    llm = LLMClient()
    try:
        return stages.run_synthesize(
            run_id, req.num_docs, req.seed, llm, req.privacy_safe, req.generator
        )
    except stages.RunNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    except stages.StageFailure as exc:
        body = StageErrorBody(stage=exc.stage, error=exc.error, hint=exc.hint)
        return JSONResponse(status_code=exc.http_status, content=body.model_dump())


@app.get("/api/runs")
def runs_list():
    return storage.list_runs()


@app.get("/api/runs/{run_id}")
def run_get(run_id: str):
    try:
        return storage.load_manifest(run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="run not found")


@app.get("/api/runs/{run_id}/dataset")
def run_dataset(run_id: str):
    try:
        manifest = storage.load_manifest(run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="run not found")
    rdir = storage.run_dir(run_id)
    dataset = [json.loads((rdir / f"doc_{d['index']}.json").read_text()) for d in manifest["docs"]]
    return JSONResponse(
        dataset,
        headers={"Content-Disposition": f'attachment; filename="{run_id}_dataset.json"'},
    )


_ARTIFACTS = {
    "json": ("doc_{i}.json", "application/json"),
    "tex": ("doc_{i}.tex", "text/plain"),
    "pdf": ("doc_{i}.pdf", "application/pdf"),
    "png": ("doc_{i}.png", "image/png"),
}


@app.get("/api/runs/{run_id}/docs/{index}/{kind}")
def doc_artifact(run_id: str, index: int, kind: str):
    if kind not in _ARTIFACTS:
        raise HTTPException(status_code=404, detail="unknown artifact type")
    fname, media = _ARTIFACTS[kind]
    try:
        path = storage.run_dir(run_id) / fname.format(i=index)
    except ValueError:
        raise HTTPException(status_code=404, detail="run not found")
    if not path.exists():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, media_type=media, filename=path.name)


# ---------------------------------------------------------------- claw

@app.post("/api/claw/chat")
def claw_chat(req: ClawChatRequest):
    try:
        storage.load_manifest(req.run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="run not found")
    return handle_claw_chat(req.run_id, req.message)


# ---------------------------------------------------------------- evals

@app.post("/api/eval/run")
def eval_run(req: EvalRequest):
    try:
        manifest = storage.load_manifest(req.run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="run not found")

    model_cfg = req.model_config_
    if req.mode == "model":
        if model_cfg is None:
            raise HTTPException(status_code=400, detail="model_config is required for mode='model'")
        try:
            model_cfg = resolve_model_config(model_cfg)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    rdir = storage.run_dir(req.run_id)
    doc_results = run_eval(
        rdir, manifest, req.mode, model_cfg, req.predictions, req.doc_indices
    )
    result = {
        "eval_id": storage.new_id("eval"),
        "run_id": req.run_id,
        "created_at": storage.now_iso(),
        "mode": req.mode,
        "model_name": model_cfg.model if model_cfg else None,
        "docs": doc_results,
        "aggregate": aggregate(doc_results),
    }
    storage.save_eval(result)
    return result


@app.get("/api/evals")
def evals_list():
    return storage.list_evals()


@app.get("/api/evals/{eval_id}")
def eval_get(eval_id: str):
    try:
        return storage.load_eval(eval_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="eval not found")


@app.get("/api/leaderboard")
def leaderboard():
    """Rank models by mean fuzzy field accuracy across persisted evals."""
    rows = []
    for summary in storage.list_evals():
        model = summary.get("model_name") or "upload"
        agg = summary.get("aggregate") or {}
        docs = agg.get("docs_evaluated", 0)
        if not docs:
            continue
        rows.append({
            "model_name": model,
            "eval_id": summary.get("eval_id"),
            "created_at": summary.get("created_at"),
            "field_accuracy": agg.get("field_accuracy"),
            "fuzzy_field_accuracy": agg.get("fuzzy_field_accuracy"),
            "cer": agg.get("cer"),
            "wer": agg.get("wer"),
            "structure_f1": agg.get("structure_f1"),
            "docs_evaluated": docs,
        })
    rows.sort(key=lambda r: (r["fuzzy_field_accuracy"] or 0.0, r["field_accuracy"] or 0.0), reverse=True)
    return rows


@app.post("/api/evals/compare")
def evals_compare(req: CompareEvalsRequest):
    try:
        a = storage.load_eval(req.eval_a)
        b = storage.load_eval(req.eval_b)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"eval not found: {exc}")
    return rigor.compare_evals(a, b)


@app.post("/api/evals/{eval_id}/gate")
def eval_gate(eval_id: str, req: QualityGateRequest):
    try:
        result = storage.load_eval(eval_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="eval not found")
    return rigor.quality_gate(result.get("aggregate", {}), req.thresholds)


# ---------------------------------------------------------------- static site

if FRONTEND_DIST.exists():
    app.mount("/legacy", StaticFiles(directory=str(LEGACY_STATIC), html=True), name="legacy")
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="spa")
else:
    app.mount("/", StaticFiles(directory=str(LEGACY_STATIC), html=True), name="static")
