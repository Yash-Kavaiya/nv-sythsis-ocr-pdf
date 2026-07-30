"""Stage status helpers and run creation for the NeMo E2E wizard."""
from __future__ import annotations

import json
from typing import Any

from .. import storage
from ..models import CurateRequest
from . import curator, hf_loader

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
