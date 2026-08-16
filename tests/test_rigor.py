"""Evaluator rigor tests: run compare, quality gate, paired-flip regression."""
from app.evals import rigor


def _eval(eval_id, model, accuracies):
    docs = []
    for i, acc in enumerate(accuracies):
        docs.append({
            "index": i,
            "field_accuracy": acc,
            "fuzzy_field_accuracy": acc,
            "cer": 1.0 - acc,
            "wer": 1.0 - acc,
            "structure_f1": acc,
        })
    return {
        "eval_id": eval_id,
        "model_name": model,
        "docs": docs,
        "aggregate": {
            "field_accuracy": round(sum(a for _, a in enumerate(accuracies)) / len(accuracies), 4),
            "fuzzy_field_accuracy": round(sum(accuracies) / len(accuracies), 4),
            "cer": round(sum(1.0 - a for a in accuracies) / len(accuracies), 4),
            "wer": round(sum(1.0 - a for a in accuracies) / len(accuracies), 4),
            "structure_f1": round(sum(accuracies) / len(accuracies), 4),
            "docs_evaluated": len(accuracies),
        },
    }


def test_compare_evals_detects_improvement():
    a = _eval("eval_a", "model-A", [0.80, 0.82, 0.79])
    b = _eval("eval_b", "model-B", [0.95, 0.93, 0.97])
    out = rigor.compare_evals(a, b)
    assert out["verdict"] == "B improved over A"
    assert out["metrics"]["field_accuracy"]["delta_b_minus_a"] > 0
    assert out["metrics"]["cer"]["delta_b_minus_a"] < 0  # lower CER is better
    assert out["metrics"]["field_accuracy"]["wins_b"] == 3
    assert out["docs_shared"] == 3


def test_compare_evals_regression_when_worse():
    a = _eval("eval_a", "model-A", [0.90, 0.92, 0.91])
    b = _eval("eval_b", "model-B", [0.60, 0.65, 0.62])
    out = rigor.compare_evals(a, b)
    assert out["verdict"] == "A better than B"
    assert out["metrics"]["field_accuracy"]["delta_b_minus_a"] < 0


def test_paired_flip_pvalue_significant():
    # 9 wins for B, 1 win for A -> sign test p < 0.05.
    a = _eval("a", "A", [0.5] * 10)
    accs_b = [0.9] * 9 + [0.3]
    b = _eval("b", "B", accs_b)
    out = rigor.compare_evals(a, b)
    assert out["metrics"]["field_accuracy"]["wins_b"] == 9
    assert out["metrics"]["field_accuracy"]["p_value"] < 0.05
    assert "field_accuracy" in out["significant_metrics"]


def test_quality_gate_pass_and_fail():
    good = {"field_accuracy": 0.95, "fuzzy_field_accuracy": 0.97, "cer": 0.03, "wer": 0.06, "structure_f1": 0.93}
    assert rigor.quality_gate(good)["gate"] == "GO"

    bad = {"field_accuracy": 0.70, "fuzzy_field_accuracy": 0.80, "cer": 0.20, "wer": 0.30, "structure_f1": 0.60}
    out = rigor.quality_gate(bad)
    assert out["gate"] == "NO-GO"
    assert "field_accuracy" in out["failed"]

    custom = rigor.quality_gate({"field_accuracy": 0.70}, {"field_accuracy": 0.60})
    assert custom["gate"] == "GO"


def test_quality_gate_empty_inconclusive():
    assert rigor.quality_gate({})["gate"] == "INCONCLUSIVE"
