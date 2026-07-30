"""Stage status helpers and run creation for the NeMo E2E wizard."""
from __future__ import annotations

import json
from typing import Any

from .. import storage
from ..latex.harness import generate_tex
from ..models import CurateRequest, PipelineRequest
from ..pdfgen.compiler import create_pdf, pdf_to_png
from . import curator, designer, hf_loader, synthesizer
from .llm import LLMClient

STAGE_ORDER = ["curator", "designer", "synthesizer", "claw", "evaluator"]

_DOWNSTREAM_STALE = {
    "curator": ["designer", "synthesizer"],
    "designer": ["synthesizer"],
}


class StageFailure(Exception):
    def __init__(self, stage: str, error: str, hint: str = "", http_status: int = 502):
        self.stage = stage
        self.error = error
        self.hint = hint
        self.http_status = http_status
        super().__init__(error)


class RunNotFoundError(Exception):
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(run_id)


def _append_stage_report(manifest: dict[str, Any], stage: str, detail: dict) -> None:
    stages = list(manifest.get("stages", []))
    report = {"stage": stage, "detail": detail}
    for i, entry in enumerate(stages):
        if entry.get("stage") == stage:
            stages[i] = report
            break
    else:
        stages.append(report)
    manifest["stages"] = stages


def _fail_stage(manifest: dict[str, Any], stage: str, error: str, hint: str = "", http_status: int = 502) -> None:
    set_stage_status(manifest, stage, "error", error=error)
    if manifest.get("stage_error"):
        manifest["stage_error"]["hint"] = hint
    storage.save_manifest(manifest)
    raise StageFailure(stage, error, hint=hint, http_status=http_status)


def empty_manifest(run_id: str, request: dict | None = None) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "created_at": storage.now_iso(),
        "request": request or {},
        "schema": {},
        "stages": [],
        "stage_status": {stage: "idle" for stage in STAGE_ORDER},
        "stage_error": None,
        "docs": [],
        "llm_backed": False,
    }


def set_stage_status(
    manifest: dict[str, Any],
    stage: str,
    status: str,
    detail: dict | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    stage_status = dict(manifest.get("stage_status", {}))
    stage_status[stage] = status
    manifest["stage_status"] = stage_status

    if detail is not None:
        stages = list(manifest.get("stages", []))
        for i, report in enumerate(stages):
            if report.get("stage") == stage:
                stages[i] = {"stage": stage, "detail": detail}
                break
        else:
            stages.append({"stage": stage, "detail": detail})
        manifest["stages"] = stages

    if error is not None:
        manifest["stage_error"] = {"stage": stage, "error": error, "hint": ""}
    elif status != "error":
        manifest["stage_error"] = None

    return manifest


def create_run(prompt: str = "", source_type: str = "empty") -> dict[str, Any]:
    run_id = storage.new_id("run")
    request = {"prompt": prompt, "source_type": source_type}
    manifest = empty_manifest(run_id, request)
    storage.save_manifest(manifest)
    return manifest


def _mark_done_downstream_stale(manifest: dict[str, Any], from_stage: str) -> dict[str, Any]:
    targets = _DOWNSTREAM_STALE.get(from_stage, [])
    stage_status = dict(manifest.get("stage_status", {}))
    for stage in targets:
        if stage_status.get(stage) == "done":
            stage_status[stage] = "stale"
    manifest["stage_status"] = stage_status
    return manifest


def run_curate(run_id: str, req: CurateRequest) -> dict[str, Any]:
    try:
        manifest = storage.load_manifest(run_id)
    except (FileNotFoundError, ValueError):
        raise RunNotFoundError(run_id)

    manifest = _mark_done_downstream_stale(manifest, "curator")
    manifest = set_stage_status(manifest, "curator", "running")
    storage.save_manifest(manifest)

    if req.source_type == "huggingface":
        if not req.hf_dataset:
            _fail_stage(
                manifest,
                "curator",
                "hf_dataset is required for huggingface source",
                hint="Provide hf_dataset in the curate request.",
                http_status=400,
            )
        try:
            seed_records = hf_loader.load_hf_rows(req.hf_dataset, req.hf_config, req.hf_split, limit=50)
        except Exception as exc:
            _fail_stage(
                manifest,
                "curator",
                f"HuggingFace load failed: {exc}",
                hint="Check dataset name, config, and network access.",
                http_status=502,
            )
        seed_detail = {"source": req.hf_dataset, "rows": len(seed_records)}
    elif req.source_type == "sample":
        try:
            seed_records = hf_loader.load_sample_seed()
        except FileNotFoundError as exc:
            _fail_stage(
                manifest,
                "curator",
                f"Sample corpus not found: {exc}",
                hint="Ensure app/data/sample_seed.json exists.",
                http_status=502,
            )
        except json.JSONDecodeError as exc:
            _fail_stage(
                manifest,
                "curator",
                f"Sample corpus is invalid JSON: {exc}",
                hint="Repair app/data/sample_seed.json.",
                http_status=502,
            )
        seed_detail = {"source": "bundled sample corpus", "rows": len(seed_records)}
    else:
        seed_records = []
        seed_detail = {"source": "empty (prompt only)", "rows": 0}

    storage.write_run_json(run_id, "seed.json", seed_records)

    try:
        curated, curator_report = curator.curate(seed_records)
    except Exception as exc:
        _fail_stage(
            manifest,
            "curator",
            str(exc),
            hint="Retry curation or check seed data.",
            http_status=502,
        )

    storage.write_run_json(run_id, "curated.json", curated)
    storage.write_run_json(run_id, "reports/curator.json", curator_report)

    _append_stage_report(manifest, "seed", seed_detail)
    manifest = set_stage_status(manifest, "curator", "done", detail=curator_report)
    storage.save_manifest(manifest)
    return {"ok": True, "manifest": manifest}


def run_design(run_id: str, prompt: str, doc_type: str | None, llm: LLMClient) -> dict[str, Any]:
    try:
        manifest = storage.load_manifest(run_id)
    except (FileNotFoundError, ValueError):
        raise RunNotFoundError(run_id)

    curator_status = manifest.get("stage_status", {}).get("curator", "idle")
    if curator_status != "done":
        try:
            storage.read_run_json(run_id, "curated.json")
        except FileNotFoundError:
            _fail_stage(
                manifest,
                "designer",
                "Curator must complete before design",
                hint="Run POST /api/runs/{id}/curate first.",
                http_status=400,
            )

    manifest = _mark_done_downstream_stale(manifest, "designer")
    manifest = set_stage_status(manifest, "designer", "running")
    storage.save_manifest(manifest)

    try:
        curated = storage.read_run_json(run_id, "curated.json")
    except FileNotFoundError:
        _fail_stage(
            manifest,
            "designer",
            "curated.json not found",
            hint="Run POST /api/runs/{id}/curate first.",
            http_status=400,
        )

    stats = curator.seed_stats(curated)

    try:
        schema, design_report = designer.design_schema(prompt, stats, llm, doc_type)
    except Exception as exc:
        _fail_stage(
            manifest,
            "designer",
            str(exc),
            hint="Retry design, or set NVIDIA_API_KEY for NIM; offline keyword design is available.",
            http_status=502,
        )

    storage.write_run_json(run_id, "schema.json", schema)
    storage.write_run_json(run_id, "reports/designer.json", design_report)

    manifest["schema"] = schema
    if design_report.get("llm_backed"):
        manifest["llm_backed"] = True

    manifest = set_stage_status(manifest, "designer", "done", detail=design_report)
    storage.save_manifest(manifest)
    return {"ok": True, "manifest": manifest}


def run_synthesize(
    run_id: str,
    num_docs: int,
    seed: int | None,
    llm: LLMClient,
    privacy_safe: bool = True,
) -> dict[str, Any]:
    try:
        manifest = storage.load_manifest(run_id)
    except (FileNotFoundError, ValueError):
        raise RunNotFoundError(run_id)

    designer_status = manifest.get("stage_status", {}).get("designer", "idle")
    if designer_status != "done":
        try:
            storage.read_run_json(run_id, "schema.json")
        except FileNotFoundError:
            _fail_stage(
                manifest,
                "synthesizer",
                "Designer must complete before synthesize",
                hint="Run POST /api/runs/{id}/design first.",
                http_status=400,
            )

    manifest = set_stage_status(manifest, "synthesizer", "running")
    storage.save_manifest(manifest)

    try:
        schema = storage.read_run_json(run_id, "schema.json")
    except FileNotFoundError:
        _fail_stage(
            manifest,
            "synthesizer",
            "schema.json not found",
            hint="Run POST /api/runs/{id}/design first.",
            http_status=400,
        )

    try:
        records, synth_report = synthesizer.synthesize(schema, num_docs, llm, seed)
    except Exception as exc:
        _fail_stage(
            manifest,
            "synthesizer",
            str(exc),
            hint="Retry synthesize, or set NVIDIA_API_KEY for NIM; offline Faker synthesis is available.",
            http_status=502,
        )

    synth_report["privacy_safe"] = privacy_safe
    storage.write_run_json(run_id, "reports/synthesizer.json", synth_report)

    rdir = storage.run_dir(run_id)
    docs = []
    engines: set[str] = set()
    for i, record in enumerate(records):
        storage.write_run_json(run_id, f"doc_{i}.json", record)
        try:
            tex, attempts = generate_tex(record, schema, llm)
        except Exception as exc:
            _fail_stage(
                manifest,
                "synthesizer",
                f"LaTeX harness failed for doc {i}: {exc}",
                hint="Retry synthesize or check LaTeX template.",
                http_status=502,
            )
        (rdir / f"doc_{i}.tex").write_text(tex)
        pdf_path = rdir / f"doc_{i}.pdf"
        try:
            engine = create_pdf(
                tex, schema["doc_type"], record, schema.get("currency", "$"), str(pdf_path)
            )
        except Exception as exc:
            _fail_stage(
                manifest,
                "synthesizer",
                f"PDF generation failed for doc {i}: {exc}",
                hint="Ensure a LaTeX engine is installed or fpdf2 fallback is available.",
                http_status=502,
            )
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

    latex_detail = {
        "template": f"{schema['doc_type']}.tex.j2",
        "docs": len(docs),
        "repair_attempts": sum(d["harness_attempts"] - 1 for d in docs),
    }
    pdf_detail = {"engine": ", ".join(sorted(engines)), "docs": len(docs)}
    storage.write_run_json(run_id, "reports/pdf.json", pdf_detail)
    _append_stage_report(manifest, "latex_harness", latex_detail)
    _append_stage_report(manifest, "pdf", pdf_detail)

    manifest["docs"] = docs
    if synth_report.get("llm_backed"):
        manifest["llm_backed"] = True

    manifest = set_stage_status(manifest, "synthesizer", "done", detail=synth_report)
    storage.save_manifest(manifest)
    return {"ok": True, "manifest": manifest}


def run_pipeline_all(req: PipelineRequest, llm: LLMClient) -> dict[str, Any]:
    manifest = create_run(req.prompt, req.source_type)
    run_id = manifest["run_id"]
    manifest["request"] = req.model_dump()
    storage.save_manifest(manifest)

    curate_req = CurateRequest(
        source_type=req.source_type,
        hf_dataset=req.hf_dataset,
        hf_config=req.hf_config,
        hf_split=req.hf_split,
    )
    manifest = run_curate(run_id, curate_req)["manifest"]
    manifest = run_design(run_id, req.prompt, req.doc_type, llm)["manifest"]
    manifest = run_synthesize(run_id, req.num_docs, req.seed, llm)["manifest"]
    return manifest
