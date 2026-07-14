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
from .evals.metrics import aggregate
from .evals.runner import run_eval
from .latex.harness import generate_tex
from .models import EvalRequest, PipelineRequest
from .pdfgen.compiler import create_pdf, find_latex_engine, pdf_to_png
from .pipeline import curator, designer, hf_loader, synthesizer
from .pipeline.llm import LLMClient

app = FastAPI(title="NV Synthetic OCR PDF Studio", version="1.0.0")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


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
    llm = LLMClient()
    stages = []

    # 1. Seed acquisition
    if req.source_type == "huggingface":
        if not req.hf_dataset:
            raise HTTPException(status_code=422, detail="hf_dataset is required for huggingface source")
        try:
            seed_records = hf_loader.load_hf_rows(req.hf_dataset, req.hf_config, req.hf_split, limit=50)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"HuggingFace load failed: {exc}")
        stages.append({"stage": "seed", "detail": {"source": req.hf_dataset, "rows": len(seed_records)}})
    elif req.source_type == "sample":
        seed_records = hf_loader.load_sample_seed()
        stages.append({"stage": "seed", "detail": {"source": "bundled sample corpus", "rows": len(seed_records)}})
    else:
        seed_records = []
        stages.append({"stage": "seed", "detail": {"source": "empty (prompt only)", "rows": 0}})

    # 2. NeMo Curator
    curated, curator_report = curator.curate(seed_records)
    stages.append({"stage": "curator", "detail": curator_report})

    # 3. NeMo Data Designer
    stats = curator.seed_stats(curated)
    schema, design_report = designer.design_schema(req.prompt, stats, llm, req.doc_type)
    stages.append({"stage": "designer", "detail": design_report})

    # 4. NeMo Synthesizer -> JSON ground truth
    records, synth_report = synthesizer.synthesize(schema, req.num_docs, llm, req.seed)
    stages.append({"stage": "synthesizer", "detail": synth_report})

    # 5. LaTeX agent harness + 6. PDF
    run_id = storage.new_id("run")
    rdir = storage.run_dir(run_id)
    rdir.mkdir(parents=True, exist_ok=True)

    docs = []
    engines = set()
    for i, record in enumerate(records):
        (rdir / f"doc_{i}.json").write_text(json.dumps(record, indent=2, default=str))
        tex, attempts = generate_tex(record, schema, llm)
        (rdir / f"doc_{i}.tex").write_text(tex)
        pdf_path = rdir / f"doc_{i}.pdf"
        engine = create_pdf(tex, schema["doc_type"], record, schema.get("currency", "$"), str(pdf_path))
        engines.add(engine)
        png_path = rdir / f"doc_{i}.png"
        has_png = pdf_to_png(str(pdf_path), str(png_path))
        docs.append({
            "index": i,
            "json_path": f"/api/runs/{run_id}/docs/{i}/json",
            "tex_path": f"/api/runs/{run_id}/docs/{i}/tex",
            "pdf_path": f"/api/runs/{run_id}/docs/{i}/pdf",
            "png_path": f"/api/runs/{run_id}/docs/{i}/png" if has_png else None,
            "harness_attempts": attempts,
            "pdf_engine": engine,
        })
    stages.append({"stage": "latex_harness", "detail": {
        "template": f"{schema['doc_type']}.tex.j2",
        "docs": len(docs),
        "repair_attempts": sum(d["harness_attempts"] - 1 for d in docs),
    }})
    stages.append({"stage": "pdf", "detail": {"engine": ", ".join(sorted(engines)), "docs": len(docs)}})

    manifest = {
        "run_id": run_id,
        "created_at": storage.now_iso(),
        "request": req.model_dump(),
        "schema": schema,
        "stages": stages,
        "docs": docs,
        "llm_backed": bool(design_report.get("llm_backed") or synth_report.get("llm_backed")),
    }
    storage.save_manifest(manifest)
    return manifest


# ---------------------------------------------------------------- runs & artifacts

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


# ---------------------------------------------------------------- evals

@app.post("/api/eval/run")
def eval_run(req: EvalRequest):
    try:
        manifest = storage.load_manifest(req.run_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="run not found")

    rdir = storage.run_dir(req.run_id)
    doc_results = run_eval(
        rdir, manifest, req.mode, req.model_config_, req.predictions, req.doc_indices
    )
    result = {
        "eval_id": storage.new_id("eval"),
        "run_id": req.run_id,
        "created_at": storage.now_iso(),
        "mode": req.mode,
        "model_name": req.model_config_.model if req.model_config_ else None,
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


# ---------------------------------------------------------------- static site

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
