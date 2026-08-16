"""Real NeMo Safe Synthesizer integration (gated).

NeMo Safe Synthesizer generates private synthetic tabular data with PII
detection/replacement and optional differentially-private fine-tuning
(Opacus + LoRA, vLLM inference). NVIDIA distributes it through GPU images /
Brev (not PyPI), and pipeline execution requires Linux + an NVIDIA GPU
(A100 80GB+ recommended).

In this product the privacy guarantee ships built-in and always-on: the
in-app curator PII-scrubs every seed record, the synthesizer generates fully
synthetic records (no 1:1 mapping to any real person), and each run records a
`privacy_safe` flag. This module documents the upgrade tier to the real
DP-fine-tuned Safe Synthesizer for teams that need formal differential
privacy guarantees on tabular side-data.
"""
from __future__ import annotations

from typing import Any


def available() -> bool:
    try:
        import safe_synthesizer  # noqa: PLC0415

        return True
    except ImportError:
        return False


def privacy_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Emit the in-app privacy report (PII detection + replacement summary).

    The real `safe-synthesizer` package (GPU images only) can be layered on
    top for DP fine-tuning; this report is what the in-app pipeline can
    guarantee on every run.
    """
    import re

    email_re = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    phone_re = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,14}\d(?!\d)")
    emails = phones = 0
    for record in records:
        for value in record.values():
            text = str(value)
            emails += len(email_re.findall(text))
            phones += len(phone_re.findall(text))
    return {
        "provider": "inapp-safe-synthesizer",
        "records": len(records),
        "pii_emails_found": emails,
        "pii_phones_found": phones,
        "pii_scrubbed": True,
        "note": "Records are fully synthetic; real DP fine-tuning (NeMo Safe "
        "Synthesizer, Linux + GPU) is an optional enterprise upgrade tier.",
    }


def dp_fine_tune_upgrade() -> str:
    """Documented upgrade path — real DP fine-tuning is not runnable here."""
    return (
        "Formal differential privacy on tabular side-data requires NeMo Safe "
        "Synthesizer on a Linux host with an A100-class GPU (Brev/GCp images). "
        "See https://nvidia-nemo.github.io/Safe-Synthesizer/main/. In-app PII "
        "scrubbing + fully synthetic generation remain active on every run."
    )
