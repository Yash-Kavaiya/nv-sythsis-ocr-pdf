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


def _within(path: Path, base: Path) -> bool:
    """True iff `path` is `base` itself or nested under it (no prefix-sibling escape)."""
    base = base.resolve()
    path = path.resolve()
    return path == base or base in path.parents


def run_dir(run_id: str) -> Path:
    path = (RUNS_DIR / run_id).resolve()
    if not _within(path, RUNS_DIR):
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


def list_runs() -> list[dict[str, Any]]:
    out = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), reverse=True):
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
    return out


def save_eval(result: dict[str, Any]) -> None:
    EVALS_DIR.mkdir(parents=True, exist_ok=True)
    (EVALS_DIR / f"{result['eval_id']}.json").write_text(json.dumps(result, indent=2, default=str))


def load_eval(eval_id: str) -> dict[str, Any]:
    path = (EVALS_DIR / f"{eval_id}.json").resolve()
    if not _within(path, EVALS_DIR) or not path.exists():
        raise FileNotFoundError(eval_id)
    return json.loads(path.read_text())


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
