"""Evaluator rigor — the pieces of NeMo Evaluator (nel) that transfer to OCR.

The real `nel` framework is built for LLM benchmarks (17 built-in suites,
SLURM/K8s backends). We port its three most valuable concepts in-app so the
"the dataset/model improved" claim is *tested*, not vibes:

1. run comparison  — per-metric deltas between two eval runs (like `nel compare`)
2. paired flip     — sign test over per-document scores (binomial, McNemar-style)
3. quality gates   — GO / NO-GO / INCONCLUSIVE from thresholds (like `nel gate`)
"""
from __future__ import annotations

from math import comb
from typing import Any, Optional

METRICS = ["field_accuracy", "fuzzy_field_accuracy", "cer", "wer", "structure_f1"]

# Higher-is-better metrics for delta/paired-flip semantics.
_HIGHER_BETTER = {"field_accuracy", "fuzzy_field_accuracy", "structure_f1"}


def _doc_scores(eval_result: dict[str, Any]) -> dict[int, dict[str, float]]:
    """eval_id -> per-doc metrics (best effort; errors are skipped)."""
    out: dict[int, dict[str, float]] = {}
    for doc in eval_result.get("docs", []):
        idx = doc.get("index")
        if idx is None or doc.get("error"):
            continue
        scores = {m: float(doc.get(m, 0.0)) for m in METRICS}
        out[idx] = scores
    return out


def _flip(wins_a: int, wins_b: int, ties: int) -> float:
    """Two-sided p-value of the sign test (McNemar's exact binomial).

    H0: A and B are equally likely to win a document (p = 0.5).
    Returns the probability of observing a split at least as extreme.
    """
    n = wins_a + wins_b
    if n == 0:
        return 1.0
    k = min(wins_a, wins_b)
    p_value = 0.0
    for i in range(k + 1):
        p_value += comb(n, i) * (0.5**n)
    return min(1.0, 2.0 * p_value)


def compare_evals(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Compare two persisted eval results, `nel compare` style.

    Returns per-metric deltas (b - a), direction-aware (lower CER/WER is
    better), a paired sign test per metric, and an overall verdict.
    """
    scores_a = _doc_scores(a)
    scores_b = _doc_scores(b)
    shared = sorted(set(scores_a) & set(scores_b))
    metrics_out: dict[str, Any] = {}
    for metric in METRICS:
        agg_a = a.get("aggregate", {}).get(metric)
        agg_b = b.get("aggregate", {}).get(metric)
        delta = round(agg_b - agg_a, 4) if agg_a is not None and agg_b is not None else None
        wins_a = wins_b = ties = 0
        for idx in shared:
            sa, sb = scores_a[idx][metric], scores_b[idx][metric]
            better_in_b = sb > sa if metric in _HIGHER_BETTER else sb < sa
            worse_in_b = sb < sa if metric in _HIGHER_BETTER else sb > sa
            if better_in_b:
                wins_b += 1
            elif worse_in_b:
                wins_a += 1
            else:
                ties += 1
        metrics_out[metric] = {
            "delta_b_minus_a": delta,
            "docs_shared": len(shared),
            "wins_b": wins_b,
            "wins_a": wins_a,
            "ties": ties,
            "p_value": round(_flip(wins_a, wins_b, ties), 4),
        }
    improved = sum(1 for m in METRICS if (metrics_out[m]["delta_b_minus_a"] or 0) > 0)
    worsened = sum(1 for m in METRICS if (metrics_out[m]["delta_b_minus_a"] or 0) < 0)
    sig = [m for m in METRICS if metrics_out[m]["p_value"] < 0.05]
    if improved > worsened:
        verdict = "B improved over A"
    elif worsened > improved:
        verdict = "A better than B"
    else:
        verdict = "no consistent difference"
    return {
        "eval_a": a.get("eval_id"),
        "eval_b": b.get("eval_id"),
        "model_a": a.get("model_name"),
        "model_b": b.get("model_name"),
        "metrics": metrics_out,
        "docs_shared": len(shared),
        "significant_metrics": sig,
        "verdict": verdict,
    }


def quality_gate(
    aggregate: dict[str, float],
    thresholds: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """GO / NO-GO / INCONCLUSIVE from per-metric thresholds, `nel gate` style.

    Default thresholds: field accuracy >= 0.90, fuzzy >= 0.95, CER <= 0.05,
    WER <= 0.10, structure F1 >= 0.90. A metric that fails its threshold is a
    NO-GO; metrics with no threshold are INCONCLUSIVE but don't fail the gate.
    """
    defaults = {
        "field_accuracy": 0.90,
        "fuzzy_field_accuracy": 0.95,
        "cer": 0.05,  # lower is better
        "wer": 0.10,  # lower is better
        "structure_f1": 0.90,
    }
    thresholds = thresholds or {}
    checks = []
    failures = []
    for metric in METRICS:
        if metric not in aggregate or aggregate[metric] is None:
            continue
        thr = thresholds.get(metric, defaults[metric])
        value = float(aggregate[metric])
        passed = value <= thr if metric not in _HIGHER_BETTER else value >= thr
        checks.append({"metric": metric, "value": value, "threshold": thr, "passed": passed})
        if not passed:
            failures.append(metric)
    if not checks:
        return {"gate": "INCONCLUSIVE", "reason": "no metrics to evaluate", "checks": []}
    if failures:
        return {
            "gate": "NO-GO",
            "reason": f"failing metrics: {', '.join(failures)}",
            "checks": checks,
            "failed": failures,
        }
    return {"gate": "GO", "reason": "all checked metrics pass", "checks": checks, "failed": []}
