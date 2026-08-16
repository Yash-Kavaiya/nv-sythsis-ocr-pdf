"""Provider registry: which engine backs each NeMo stage.

Every stage can run on the in-app implementation (always available, offline)
or on a real NVIDIA NeMo package when the environment supports it. This
module answers "what should stage X use right now?" so the rest of the app
never has to guess.

Resolution rules (per stage):
  curator     -> "nemo" only when NEMO_CURATOR=1 and nemo_curator imports
                 (real NeMo Curator is Linux/Dask/GPU-oriented).
  designer    -> "nemo" only when the real `data-designer` package is
                 installed AND an NVIDIA API key is set.
  synthesizer -> same as designer (real Data Designer is used at record
                 generation time — the schema stays in-app).
  evaluator   -> "nemo" only when the real `nel` (Nemo Evaluator) is
                 importable; the in-app evaluator ports its concepts
                 (compare, quality gate) regardless.

"auto" picks nemo when available, else inapp. An explicit request of "nemo"
falls back to inapp with the reason recorded, so a missing key or package
never breaks a run.
"""
from __future__ import annotations

import importlib
import os
from typing import Any

STAGES = ("curator", "designer", "synthesizer", "evaluator")


def _pkg_available(pkg: str) -> bool:
    try:
        importlib.import_module(pkg)
        return True
    except ImportError:
        return False


def _nvidia_key() -> bool:
    return bool(os.environ.get("NVIDIA_API_KEY"))


def _curator_available() -> bool:
    return os.environ.get("NEMO_CURATOR", "") == "1" and _pkg_available("nemo_curator")


def _data_designer_available() -> bool:
    return _pkg_available("data_designer") and _nvidia_key()


def _nel_available() -> bool:
    return _pkg_available("nel")


def _availability(stage: str) -> tuple[bool, str]:
    """(nemo_available, reason) for a stage."""
    if stage == "curator":
        if _curator_available():
            return True, "real nemo-curator package enabled (NEMO_CURATOR=1)"
        if os.environ.get("NEMO_CURATOR") == "1":
            return False, "nemo-curator not importable (Linux/Dask/GPU required)"
        return False, "NEMO_CURATOR not enabled; in-app curator used"
    if stage in ("designer", "synthesizer"):
        if _data_designer_available():
            return True, "real data-designer package + NVIDIA_API_KEY"
        if _pkg_available("data_designer"):
            return False, "data-designer installed but NVIDIA_API_KEY not set"
        return False, "data-designer not installed (pip install data-designer)"
    if stage == "evaluator":
        if _nel_available():
            return True, "real nel (Nemo Evaluator) importable"
        return False, "nel not installed; in-app evaluator with ported rigor"
    return False, f"unknown stage {stage}"


def resolve(stage: str, requested: str = "auto") -> dict[str, Any]:
    """Decide the engine for a stage.

    requested: "auto" | "inapp" | "nemo"
    Returns {"provider": "inapp"|"nemo", "reason": str}.
    """
    if stage not in STAGES:
        return {"provider": "inapp", "reason": f"unknown stage {stage}"}
    if requested == "inapp":
        return {"provider": "inapp", "reason": "explicitly in-app"}
    nemo_ok, reason = _availability(stage)
    if requested == "nemo" and not nemo_ok:
        return {"provider": "inapp", "reason": f"nemo requested but unavailable: {reason}"}
    if nemo_ok:
        return {"provider": "nemo", "reason": reason}
    return {"provider": "inapp", "reason": reason}


def status() -> dict[str, Any]:
    """Snapshot of every stage's current engine + reason (for /api/health)."""
    return {
        stage: {"provider": resolve(stage)["provider"], "reason": resolve(stage)["reason"]}
        for stage in STAGES
    }
