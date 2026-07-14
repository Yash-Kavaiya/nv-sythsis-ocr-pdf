"""OCR evaluation metrics: field accuracy (exact + fuzzy), CER/WER over the
flattened document text, and a structure F1 over the JSON key tree."""
from __future__ import annotations

import re
from typing import Any


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _norm_text(value: Any) -> str:
    text = str(value if value is not None else "").lower()
    text = re.sub(r"[,\s]+", " ", text).strip()
    # Normalize money-ish strings: 1,234.50 / $1234.5 -> 1234.50
    plain = text.replace("$", "").replace(" ", "")
    try:
        return f"{float(plain):.2f}"
    except ValueError:
        return text


def similarity(a: Any, b: Any) -> float:
    sa, sb = _norm_text(a), _norm_text(b)
    if sa == sb:
        return 1.0
    if not sa and not sb:
        return 1.0
    denom = max(len(sa), len(sb))
    return 1.0 - levenshtein(sa, sb) / denom if denom else 0.0


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested JSON into dot/bracket paths -> leaf values."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def cer(reference: str, hypothesis: str) -> float:
    ref = re.sub(r"\s+", " ", reference.strip())
    hyp = re.sub(r"\s+", " ", hypothesis.strip())
    if not ref:
        return 0.0 if not hyp else 1.0
    return min(1.0, levenshtein(ref, hyp) / len(ref))


def wer(reference: str, hypothesis: str) -> float:
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    prev = list(range(len(hyp_words) + 1))
    for i, rw in enumerate(ref_words, 1):
        curr = [i]
        for j, hw in enumerate(hyp_words, 1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = curr
    return min(1.0, prev[-1] / len(ref_words))


def text_of(obj: Any) -> str:
    """Reading-order text of a JSON document (values only)."""
    return " ".join(_norm_text(v) for v in flatten(obj).values() if v not in (None, ""))


def evaluate_doc(ground_truth: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    gt_flat = flatten(ground_truth)
    pred_flat = flatten(prediction)

    fields = []
    exact = 0
    fuzzy_sum = 0.0
    for path, gt_val in gt_flat.items():
        pred_val = pred_flat.get(path)
        sim = similarity(gt_val, pred_val) if pred_val is not None else 0.0
        is_exact = pred_val is not None and _norm_text(gt_val) == _norm_text(pred_val)
        exact += is_exact
        fuzzy_sum += sim
        fields.append({
            "field": path,
            "expected": gt_val,
            "predicted": pred_val,
            "match": "exact" if is_exact else ("fuzzy" if sim >= 0.8 else "miss"),
            "similarity": round(sim, 3),
        })

    total = len(gt_flat) or 1
    gt_keys, pred_keys = set(gt_flat), set(pred_flat)
    tp = len(gt_keys & pred_keys)
    precision = tp / len(pred_keys) if pred_keys else 0.0
    recall = tp / len(gt_keys) if gt_keys else 0.0
    structure_f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "field_accuracy": round(exact / total, 4),
        "fuzzy_field_accuracy": round(fuzzy_sum / total, 4),
        "cer": round(cer(text_of(ground_truth), text_of(prediction)), 4),
        "wer": round(wer(text_of(ground_truth), text_of(prediction)), 4),
        "structure_f1": round(structure_f1, 4),
        "matched_fields": exact,
        "total_fields": total,
        "fields": fields,
    }


def aggregate(doc_results: list[dict[str, Any]]) -> dict[str, float]:
    scored = [d for d in doc_results if not d.get("error")]
    if not scored:
        return {}
    keys = ["field_accuracy", "fuzzy_field_accuracy", "cer", "wer", "structure_f1"]
    agg = {k: round(sum(d[k] for d in scored) / len(scored), 4) for k in keys}
    agg["docs_evaluated"] = len(scored)
    agg["docs_failed"] = len(doc_results) - len(scored)
    return agg
