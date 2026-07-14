"""NeMo-Curator-style curation for seed records.

Mirrors the classic Curator stages on a small scale: unicode/whitespace
normalization, exact dedup, near-dedup on normalized text, length filtering,
and PII scrubbing. Returns curated records plus a per-stage report.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,14}\d(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        value = unicodedata.normalize("NFKC", value)
        value = re.sub(r"[ \t]+", " ", value).strip()
    elif isinstance(value, dict):
        value = {k: _normalize(v) for k, v in value.items()}
    elif isinstance(value, list):
        value = [_normalize(v) for v in value]
    return value


def _scrub_pii(value: Any) -> Any:
    if isinstance(value, str):
        value = EMAIL_RE.sub("[EMAIL]", value)
        value = SSN_RE.sub("[ID]", value)
        value = PHONE_RE.sub("[PHONE]", value)
    elif isinstance(value, dict):
        value = {k: _scrub_pii(v) for k, v in value.items()}
    elif isinstance(value, list):
        value = [_scrub_pii(v) for v in value]
    return value


def _fingerprint(record: dict, loose: bool = False) -> str:
    text = json.dumps(record, sort_keys=True, default=str).lower()
    if loose:
        text = re.sub(r"[^a-z0-9]", "", text)
    return hashlib.sha256(text.encode()).hexdigest()


def curate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report: dict[str, Any] = {"input_records": len(records)}
    if not records:
        report["note"] = "empty seed - designer will work from the prompt alone"
        return [], report

    normalized = [_normalize(r) for r in records]

    seen: set[str] = set()
    deduped = []
    for r in normalized:
        fp = _fingerprint(r)
        if fp not in seen:
            seen.add(fp)
            deduped.append(r)
    report["after_exact_dedup"] = len(deduped)

    seen_loose: set[str] = set()
    near_deduped = []
    for r in deduped:
        fp = _fingerprint(r, loose=True)
        if fp not in seen_loose:
            seen_loose.add(fp)
            near_deduped.append(r)
    report["after_near_dedup"] = len(near_deduped)

    filtered = [
        r for r in near_deduped
        if len(json.dumps(r, default=str)) >= 20 and any(v not in (None, "", [], {}) for v in r.values())
    ]
    report["after_quality_filter"] = len(filtered)

    scrubbed = [_scrub_pii(r) for r in filtered]
    report["pii_scrubbed"] = True
    report["output_records"] = len(scrubbed)
    return scrubbed, report


def seed_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact summary of the curated seed corpus for the Data Designer."""
    if not records:
        return {"count": 0, "columns": []}
    columns: dict[str, str] = {}
    for r in records[:20]:
        for k, v in r.items():
            columns.setdefault(k, type(v).__name__)
    return {
        "count": len(records),
        "columns": [{"name": k, "type": t} for k, t in list(columns.items())[:30]],
        "example": records[0],
    }
