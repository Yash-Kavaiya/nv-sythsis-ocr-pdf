"""Filesystem persistence for pipeline runs and eval results."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
RUNS_DIR = DATA_DIR / "runs"
EVALS_DIR = DATA_DIR / "evals"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def run_dir(run_id: str) -> Path:
    path = (RUNS_DIR / run_id).resolve()
    if not str(path).startswith(str(RUNS_DIR.resolve())):
        raise ValueError("invalid run id")
    return path


def save_manifest(manifest: dict[str, Any]) -> None:
    d = run_dir(manifest["run_id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))


def load_manifest(run_id: str) -> dict[str, Any]:
    path = run_dir(run_id) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(run_id)
    return json.loads(path.read_text())


def _safe_run_path(run_id: str, relative: str) -> Path:
    base = run_dir(run_id)
    path = (base / relative).resolve()
    if not str(path).startswith(str(base.resolve())):
        raise ValueError("invalid path")
    return path


def write_run_json(run_id: str, relative: str, data: Any) -> None:
    path = _safe_run_path(run_id, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def read_run_json(run_id: str, relative: str) -> Any:
    path = _safe_run_path(run_id, relative)
    if not path.exists():
        raise FileNotFoundError(relative)
    return json.loads(path.read_text())


_DOWNSTREAM_STALE: dict[str, list[str]] = {
    "curator": ["designer", "synthesizer"],
    "designer": ["synthesizer"],
}


def mark_downstream_stale(manifest: dict[str, Any], from_stage: str) -> dict[str, Any]:
    targets = _DOWNSTREAM_STALE.get(from_stage, [])
    stage_status = dict(manifest.get("stage_status", {}))
    for stage in targets:
        if stage in stage_status:
            stage_status[stage] = "stale"
    manifest["stage_status"] = stage_status
    return manifest


def list_runs() -> list[dict[str, Any]]:
    out = []
    if RUNS_DIR.exists():
        for d in RUNS_DIR.iterdir():
            mpath = d / "manifest.json"
            if mpath.exists():
                m = json.loads(mpath.read_text())
                out.append({
                    "run_id": m["run_id"],
                    "created_at": m.get("created_at"),
                    "prompt": m.get("request", {}).get("prompt", ""),
                    "doc_type": m.get("schema", {}).get("doc_type"),
                    "num_docs": len(m.get("docs", [])),
                    "llm_backed": m.get("llm_backed", False),
                })
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return out


def save_eval(result: dict[str, Any]) -> None:
    EVALS_DIR.mkdir(parents=True, exist_ok=True)
    (EVALS_DIR / f"{result['eval_id']}.json").write_text(json.dumps(result, indent=2, default=str))


def load_eval(eval_id: str) -> dict[str, Any]:
    path = (EVALS_DIR / f"{eval_id}.json").resolve()
    if not str(path).startswith(str(EVALS_DIR.resolve())) or not path.exists():
        raise FileNotFoundError(eval_id)
    return json.loads(path.read_text())


def load_claw_messages(run_id: str) -> list[dict[str, Any]]:
    path = _safe_run_path(run_id, "claw/messages.json")
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_claw_messages(run_id: str, messages: list[dict[str, Any]]) -> None:
    path = _safe_run_path(run_id, "claw/messages.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2, default=str))


def list_evals() -> list[dict[str, Any]]:
    out = []
    if EVALS_DIR.exists():
        for f in sorted(EVALS_DIR.glob("eval_*.json"), reverse=True):
            e = json.loads(f.read_text())
            out.append({
                "eval_id": e["eval_id"],
                "run_id": e["run_id"],
                "created_at": e.get("created_at"),
                "mode": e.get("mode"),
                "model_name": e.get("model_name"),
                "aggregate": e.get("aggregate", {}),
            })
    return out
