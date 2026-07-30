"""Stage status helpers and run creation for the NeMo E2E wizard."""
from __future__ import annotations

from typing import Any

from .. import storage

STAGE_ORDER = ["curator", "designer", "synthesizer", "claw", "evaluator"]


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
