"""Server-side tools invoked by NeMo Claw."""
from __future__ import annotations

from typing import Any

from .. import storage
from ..models import CurateRequest, SynthesizeRequest
from ..pipeline import stages
from ..pipeline.llm import LLMClient

TOOL_NAMES = [
    "run_pipeline",
    "run_stage",
    "get_manifest",
    "get_report",
    "list_docs",
    "suggest_fix",
    "start_eval",
]

_REPORT_STAGES = ("curator", "designer", "synthesizer", "pdf")


def execute_tool(tool_name: str, args: dict[str, Any], run_id: str) -> dict[str, Any]:
    if tool_name not in TOOL_NAMES:
        return {"ok": False, "error": f"unknown tool: {tool_name}"}
    try:
        storage.load_manifest(run_id)
    except (FileNotFoundError, ValueError):
        return {"ok": False, "error": "run not found", "run_id": run_id}

    handlers = {
        "get_manifest": _get_manifest,
        "get_report": _get_report,
        "list_docs": _list_docs,
        "run_pipeline": _run_pipeline,
        "run_stage": _run_stage,
        "suggest_fix": _suggest_fix,
        "start_eval": _start_eval,
    }
    return handlers[tool_name](run_id, args or {})


def _get_manifest(run_id: str, _args: dict[str, Any]) -> dict[str, Any]:
    manifest = storage.load_manifest(run_id)
    return {"ok": True, **manifest}


def _get_report(run_id: str, args: dict[str, Any]) -> dict[str, Any]:
    stage = args.get("stage", "curator")
    if stage not in _REPORT_STAGES:
        return {"ok": False, "error": f"unknown report stage: {stage}"}
    try:
        report = storage.read_run_json(run_id, f"reports/{stage}.json")
    except FileNotFoundError:
        return {"ok": False, "error": f"report not found for stage: {stage}"}
    return {"ok": True, "stage": stage, "report": report}


def _list_docs(run_id: str, _args: dict[str, Any]) -> dict[str, Any]:
    manifest = storage.load_manifest(run_id)
    docs = manifest.get("docs", [])
    return {"ok": True, "run_id": run_id, "count": len(docs), "docs": docs}


def _run_pipeline(run_id: str, args: dict[str, Any]) -> dict[str, Any]:
    manifest = storage.load_manifest(run_id)
    req_data = {**manifest.get("request", {}), **args}
    llm = LLMClient()
    try:
        curate_req = CurateRequest(
            source_type=req_data.get("source_type", "empty"),
            hf_dataset=req_data.get("hf_dataset"),
            hf_config=req_data.get("hf_config"),
            hf_split=req_data.get("hf_split", "train"),
        )
        stages.run_curate(run_id, curate_req)
        stages.run_design(
            run_id,
            req_data.get("prompt", manifest.get("request", {}).get("prompt", "")),
            req_data.get("doc_type"),
            llm,
        )
        stages.run_synthesize(
            run_id,
            int(req_data.get("num_docs", 5)),
            req_data.get("seed"),
            llm,
            req_data.get("privacy_safe", True),
        )
    except stages.StageFailure as exc:
        return {"ok": False, "stage": exc.stage, "error": exc.error, "hint": exc.hint}
    except stages.RunNotFoundError:
        return {"ok": False, "error": "run not found"}
    return {"ok": True, "manifest": storage.load_manifest(run_id)}


def _run_stage(run_id: str, args: dict[str, Any]) -> dict[str, Any]:
    stage = args.get("stage", "")
    llm = LLMClient()
    manifest = storage.load_manifest(run_id)
    req_data = manifest.get("request", {})
    try:
        if stage == "curate":
            curate_req = CurateRequest(
                source_type=args.get("source_type", req_data.get("source_type", "empty")),
                hf_dataset=args.get("hf_dataset", req_data.get("hf_dataset")),
                hf_config=args.get("hf_config", req_data.get("hf_config")),
                hf_split=args.get("hf_split", req_data.get("hf_split", "train")),
            )
            result = stages.run_curate(run_id, curate_req)
        elif stage == "design":
            result = stages.run_design(
                run_id,
                args.get("prompt", req_data.get("prompt", "")),
                args.get("doc_type", req_data.get("doc_type")),
                llm,
            )
        elif stage == "synthesize":
            result = stages.run_synthesize(
                run_id,
                int(args.get("num_docs", req_data.get("num_docs", 5))),
                args.get("seed", req_data.get("seed")),
                llm,
                args.get("privacy_safe", req_data.get("privacy_safe", True)),
            )
        else:
            return {"ok": False, "error": "stage must be one of: curate, design, synthesize"}
    except stages.StageFailure as exc:
        return {"ok": False, "stage": exc.stage, "error": exc.error, "hint": exc.hint}
    except stages.RunNotFoundError:
        return {"ok": False, "error": "run not found"}
    return {"ok": True, "manifest": result.get("manifest", storage.load_manifest(run_id))}


def _suggest_fix(run_id: str, _args: dict[str, Any]) -> dict[str, Any]:
    manifest = storage.load_manifest(run_id)
    stage_error = manifest.get("stage_error")
    suggestions: list[str] = []
    if stage_error:
        hint = stage_error.get("hint", "")
        if hint:
            suggestions.append(hint)
        stage = stage_error.get("stage", "")
        if stage == "curator":
            suggestions.append("Re-run curation with a valid seed source.")
        elif stage == "designer":
            suggestions.append("Ensure curator completed, then retry design with a clearer prompt.")
        elif stage == "synthesizer":
            suggestions.append("Ensure designer completed, then retry synthesize with fewer docs.")
        try:
            report = storage.read_run_json(run_id, f"reports/{stage}.json")
            suggestions.append(f"Latest {stage} report available for review.")
            return {
                "ok": True,
                "stage_error": stage_error,
                "suggestions": suggestions,
                "report": report,
            }
        except FileNotFoundError:
            pass
    else:
        suggestions.append("No stage errors recorded. Pipeline may be idle or complete.")
    return {"ok": True, "stage_error": stage_error, "suggestions": suggestions}


def _start_eval(run_id: str, args: dict[str, Any]) -> dict[str, Any]:
    manifest = storage.load_manifest(run_id)
    mode = args.get("mode", "upload")
    doc_count = len(manifest.get("docs", []))
    return {
        "ok": True,
        "run_id": run_id,
        "mode": mode,
        "doc_count": doc_count,
        "eval_endpoint": "/api/eval/run",
        "deep_link": f"/eval?run_id={run_id}",
        "message": "Open the Evaluator step or POST /api/eval/run to score OCR output.",
    }
