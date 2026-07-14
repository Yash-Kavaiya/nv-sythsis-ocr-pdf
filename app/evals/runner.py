"""Eval runner: get OCR predictions for each generated document - either by
calling the user's own vision model (any OpenAI-compatible endpoint) with the
rendered page image, or from user-uploaded predictions - then score them
against the ground-truth JSON."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Optional

import httpx

from ..models import ModelConfig
from ..pipeline.llm import extract_json
from .metrics import aggregate, evaluate_doc

OCR_PROMPT = """You are an OCR extraction engine. Read the document image and extract ALL of its content \
as a single JSON object with exactly these keys: {keys}. \
"items" (when present) must be an array of objects with keys: description, quantity, unit_price, total. \
Numbers must be plain JSON numbers without currency symbols. Copy text exactly as printed. \
Output ONLY the JSON object."""


def call_vision_model(cfg: ModelConfig, png_path: str, gt_keys: list[str]) -> dict[str, Any]:
    image_b64 = base64.b64encode(Path(png_path).read_bytes()).decode()
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    payload = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "temperature": 0.0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT.format(keys=gt_keys)},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }
        ],
    }
    with httpx.Client(timeout=180) as client:
        resp = client.post(
            f"{cfg.base_url.rstrip('/')}/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    parsed = extract_json(content)
    if not isinstance(parsed, dict):
        raise ValueError("Model did not return a JSON object")
    return parsed


def run_eval(
    run_dir: Path,
    manifest: dict[str, Any],
    mode: str,
    model_cfg: Optional[ModelConfig],
    uploaded: Optional[dict[str, Any]],
    doc_indices: Optional[list[int]],
) -> list[dict[str, Any]]:
    gt_keys = [f["name"] for f in manifest.get("schema", {}).get("fields", [])]
    results = []
    for doc in manifest["docs"]:
        idx = doc["index"]
        if doc_indices is not None and idx not in doc_indices:
            continue
        ground_truth = json.loads((run_dir / f"doc_{idx}.json").read_text())
        entry: dict[str, Any] = {"index": idx, "prediction": {}}
        try:
            if mode == "model":
                if model_cfg is None:
                    raise ValueError("model mode requires model_config")
                png = run_dir / f"doc_{idx}.png"
                if not png.exists():
                    raise ValueError("no rendered PNG for this document")
                prediction = call_vision_model(model_cfg, str(png), gt_keys)
            else:
                prediction = (uploaded or {}).get(str(idx))
                if prediction is None:
                    raise ValueError("no uploaded prediction for this document")
                if not isinstance(prediction, dict):
                    raise ValueError("prediction must be a JSON object")
            entry["prediction"] = prediction
            entry.update(evaluate_doc(ground_truth, prediction))
        except Exception as exc:
            entry.update({
                "error": str(exc)[:500],
                "field_accuracy": 0.0, "fuzzy_field_accuracy": 0.0,
                "cer": 1.0, "wer": 1.0, "structure_f1": 0.0,
                "matched_fields": 0, "total_fields": 0, "fields": [],
            })
        results.append(entry)
    return results


__all__ = ["run_eval", "call_vision_model", "aggregate"]
