"""Real NeMo Data Designer integration (`pip install data-designer`).

This provider translates an in-app document schema into a
``DataDesignerConfigBuilder``: structured fields (choice/percent/id/digits)
become statistical samplers, content fields (company/name/address/items/…)
become LLM-text columns backed by the configured NVIDIA model, and the
resulting records flow through the same arithmetic-consistency pass as the
in-app synthesizer so ground truth stays exact.

Design notes (learned the hard way):
- LLM columns MUST reference another column or the same prompt repeats per
  row; we add a hidden ``row_style`` category column (drop=True) and include
  it in every prompt for per-row diversity.
- Prompts must demand a bare value ("Respond with ONLY … nothing else") —
  the default model will happily write essays otherwise.
- data-designer's rich logger crashes on Windows cp1252 consoles, so this
  module forces UTF-8 stdout/stderr at import time.

Any failure (package missing, no key, validation error, LLM outage) returns
``None`` from ``generate_records`` and the caller falls back to the in-app
synthesizer, so the real NeMo path can never break a run.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Optional

from . import synthesizer

# data-designer logs with `rich`, which raises UnicodeEncodeError on Windows
# cp1252 consoles when the message contains emoji. Force UTF-8 everywhere.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_MODEL = "nvidia/nemotron-3-nano-30b-a3b"
_MODEL_ALIAS = "nvidia-ultra"  # distinct from the default "nvidia-text" alias

_STYLES = ["classic", "modern", "boutique", "established", "independent"]
_TAX_RATES = [5.0, 8.0, 10.0, 12.0, 18.0]

_ONLY = " Respond with ONLY the requested value - no explanations, no lists, no markdown."


def _model_name() -> str:
    return os.environ.get("NVIDIA_MODEL", DEFAULT_MODEL)


def _dd():
    """Lazy import; raises ImportError when data-designer isn't installed."""
    from data_designer.config import (  # noqa: PLC0415
        CategorySamplerParams,
        DataDesignerConfigBuilder,
        DatetimeSamplerParams,
        LLMTextColumnConfig,
        ModelConfig,
        SamplerColumnConfig,
        SamplerType,
        UniformSamplerParams,
        UUIDSamplerParams,
    )
    from data_designer.interface import DataDesigner  # noqa: PLC0415

    return (
        DataDesigner,
        DataDesignerConfigBuilder,
        SamplerColumnConfig,
        SamplerType,
        CategorySamplerParams,
        UniformSamplerParams,
        DatetimeSamplerParams,
        UUIDSamplerParams,
        LLMTextColumnConfig,
        ModelConfig,
    )


def _add_model_override(builder, cls_ModelConfig) -> None:
    """Pin the NVIDIA model configured via NVIDIA_MODEL under a fresh alias."""
    builder.add_model_config(
        cls_ModelConfig(
            alias=_MODEL_ALIAS,
            provider="nvidia",
            model=_model_name(),
            skip_health_check=True,
        )
    )


def _base_builder(schema: dict[str, Any]):
    (
        _DataDesigner,
        DataDesignerConfigBuilder,
        SamplerColumnConfig,
        SamplerType,
        CategorySamplerParams,
        UniformSamplerParams,
        DatetimeSamplerParams,
        UUIDSamplerParams,
        _LLMTextColumnConfig,
        ModelConfig,
    ) = _dd()
    builder = DataDesignerConfigBuilder()
    _add_model_override(builder, ModelConfig)
    # Hidden per-row style column: gives every LLM prompt a varying reference
    # (diversity + avoids data-designer's PROMPT_WITHOUT_REFERENCES warning).
    builder.add_column(
        SamplerColumnConfig(
            name="row_style",
            drop=True,
            sampler_type=SamplerType.CATEGORY,
            params=CategorySamplerParams(values=_STYLES),
        )
    )
    return builder, SamplerColumnConfig, SamplerType, CategorySamplerParams, UniformSamplerParams, DatetimeSamplerParams, UUIDSamplerParams, _LLMTextColumnConfig


def _theme(schema: dict[str, Any]) -> str:
    theme = schema.get("theme") or schema.get("doc_type", "document")
    return re.sub(r"\s+", " ", str(theme)).strip()[:200]


def _vocab(schema: dict[str, Any]) -> str:
    vocab = schema.get("item_vocabulary") or []
    return ", ".join(str(v) for v in vocab[:8]) or "products and services"


def _prompt(text: str, schema: dict[str, Any]) -> str:
    return f"{text}. Theme: {_theme(schema)}. Style: {{{{ row_style }}}}." + _ONLY


def _add_text(builder, LLMTextColumnConfig, name: str, prompt: str, schema: dict[str, Any], fallback: Optional[str] = None) -> bool:
    try:
        builder.add_column(LLMTextColumnConfig(name=name, model_alias=_MODEL_ALIAS, prompt=_prompt(prompt, schema)))
        return True
    except Exception:
        if fallback:
            builder.add_column(fallback)
            return True
        return False


def _add_sampler(builder, SamplerColumnConfig, SamplerType, params_cls, name: str, sampler_type, params) -> bool:
    try:
        builder.add_column(SamplerColumnConfig(name=name, sampler_type=sampler_type, params=params_cls(**params)))
        return True
    except Exception:
        return False


def build_builder(schema: dict[str, Any]):
    """Translate a document schema into a DataDesignerConfigBuilder.

    Returns (builder, post_process) where post_process maps a generated
    DataFrame row (dict) to a canonical in-app record. Raises on any
    configuration error so the caller can fall back.
    """
    builder, SamplerColumnConfig, SamplerType, CategorySamplerParams, UniformSamplerParams, DatetimeSamplerParams, UUIDSamplerParams, LLMTextColumnConfig = _base_builder(schema)
    doc_type = schema["doc_type"]

    for field in schema["fields"]:
        fname, ftype = field["name"], field["type"]
        try:
            if ftype.startswith("choice:"):
                values = ftype.split(":", 1)[1].split(",")
                _add_sampler(builder, SamplerColumnConfig, SamplerType, CategorySamplerParams, fname, SamplerType.CATEGORY, {"values": values})
            elif ftype == "percent":
                _add_sampler(builder, SamplerColumnConfig, SamplerType, CategorySamplerParams, fname, SamplerType.CATEGORY, {"values": _TAX_RATES})
            elif ftype == "money":
                _add_sampler(builder, SamplerColumnConfig, SamplerType, UniformSamplerParams, fname, SamplerType.UNIFORM, {"low": 10, "high": 5000})
            elif ftype == "id":
                _add_sampler(builder, SamplerColumnConfig, SamplerType, UUIDSamplerParams, fname, SamplerType.UUID, {"uppercase": True, "short_form": True})
            elif ftype == "digits4":
                _add_sampler(builder, SamplerColumnConfig, SamplerType, UniformSamplerParams, fname, SamplerType.UNIFORM, {"low": 0, "high": 9999})
            elif ftype == "date":
                if not _add_sampler(builder, SamplerColumnConfig, SamplerType, DatetimeSamplerParams, fname, SamplerType.DATETIME, {"start": "2024-01-01", "end": "2026-12-31", "unit": "D"}):
                    _add_text(builder, LLMTextColumnConfig, fname, f"A date between 2024 and 2026, formatted like 12 Mar 2025", schema)
            elif ftype == "dob":
                if not _add_sampler(builder, SamplerColumnConfig, SamplerType, DatetimeSamplerParams, fname, SamplerType.DATETIME, {"start": "1945-01-01", "end": "2008-12-31", "unit": "D"}):
                    _add_text(builder, LLMTextColumnConfig, fname, f"A date of birth between 1945 and 2008, formatted like 12 Mar 1980", schema)
            elif ftype == "name":
                _add_text(builder, LLMTextColumnConfig, fname, "A realistic full person name", schema)
            elif ftype == "company":
                _add_text(builder, LLMTextColumnConfig, fname, "A realistic small business company name", schema)
            elif ftype == "address":
                _add_text(builder, LLMTextColumnConfig, fname, "A realistic full postal address on a single line (street, city, state, postal code)", schema)
            elif ftype == "phone":
                _add_text(builder, LLMTextColumnConfig, fname, "A realistic phone number", schema)
            elif ftype == "email":
                _add_text(builder, LLMTextColumnConfig, fname, "A realistic business email address", schema)
            elif ftype == "time":
                _add_text(builder, LLMTextColumnConfig, fname, "A time of day formatted like 14:32", schema)
            elif ftype == "sentence":
                _add_text(builder, LLMTextColumnConfig, fname, "A short business subject line relevant to the theme", schema)
            elif ftype == "paragraphs":
                _add_text(builder, LLMTextColumnConfig, fname, "A formal letter body of 3 to 5 sentences relevant to the theme", schema)
            elif ftype == "line_items":
                _add_text(
                    builder,
                    LLMTextColumnConfig,
                    fname,
                    "A JSON array of 2 to 6 line items, each an object with keys "
                    'description (a real product/service from the theme, e.g. "%s"), '
                    "quantity (integer 1-12), unit_price (number), total (number). "
                    "Output ONLY the JSON array." % _vocab(schema),
                    schema,
                )
            # Unknown types are intentionally skipped; in-app fallback fills them.
        except Exception:
            continue  # never let one column break the whole run

    def post_process(row: dict[str, Any], rng: Any) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for field in schema["fields"]:
            fname, ftype = field["name"], field["type"]
            value = row.get(fname)
            if value is None or (isinstance(value, float) and value != value):  # NaN
                continue
            if ftype == "money":
                try:
                    record[fname] = round(float(value), 2)
                except (TypeError, ValueError):
                    record[fname] = value
            elif ftype == "percent":
                try:
                    record[fname] = float(value)
                except (TypeError, ValueError):
                    record[fname] = value
            elif ftype == "digits4":
                try:
                    record[fname] = f"{int(float(value)):04d}"
                except (TypeError, ValueError):
                    record[fname] = str(value)[:4]
            elif ftype == "id":
                record[fname] = _short_id(str(value))
            elif ftype == "date" or ftype == "dob":
                record[fname] = _format_date(value)
            elif ftype == "time":
                record[fname] = _format_time(value)
            elif ftype == "line_items":
                items = _parse_items(value, schema, rng)
                if items:
                    record[fname] = items
            elif ftype == "paragraphs":
                text = str(value).strip().strip('"')
                record[fname] = text
            else:
                record[fname] = str(value).strip() if value is not None else value
        record = synthesizer._enforce_consistency(record, doc_type)
        # Mirror the in-app synthesizer: due_date must follow invoice_date.
        if "invoice_date" in record and "due_date" in record:
            try:
                from datetime import datetime, timedelta

                base = datetime.strptime(record["invoice_date"], "%d %b %Y")
                record["due_date"] = (
                    base + timedelta(days=rng.choice([15, 30, 45, 60]))
                ).strftime("%d %b %Y")
            except ValueError:
                pass
        return record

    return builder, post_process


def _short_id(value: str) -> str:
    letters = re.sub(r"[^A-Z]", "", value.upper()) or "AB"
    digits = re.sub(r"[^0-9]", "", value) or "12345"
    return f"{letters[:2]}-{digits[:5]}"


def _format_date(value: Any) -> str:
    import datetime as dt

    try:
        if hasattr(value, "to_pydatetime"):  # pandas Timestamp
            value = value.to_pydatetime()
        elif hasattr(value, "item"):  # numpy.datetime64
            value = value.item()
        if isinstance(value, dt.datetime):
            return value.strftime("%d %b %Y")
        if isinstance(value, dt.date):
            return value.strftime("%d %b %Y")
    except Exception:
        pass
    text = str(value).strip()
    try:
        return dt.datetime.fromisoformat(text).strftime("%d %b %Y")
    except ValueError:
        return text[:20]


def _format_time(value: Any) -> str:
    import datetime as dt

    try:
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        elif hasattr(value, "item"):
            value = value.item()
        if isinstance(value, (dt.datetime, dt.time)):
            return value.strftime("%H:%M")
    except Exception:
        pass
    text = str(value).strip()
    if re.match(r"^\d{1,2}:\d{2}", text):
        return text[:5]
    return text[:8]


def _parse_items(value: Any, schema: dict[str, Any], rng: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        raw = value
    else:
        text = str(value).strip()
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            raw = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    items = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        desc = it.get("description") or it.get("name")
        qty = it.get("quantity")
        unit = it.get("unit_price")
        if not desc or qty is None or unit is None:
            continue
        try:
            qty = int(qty)
            unit = round(float(unit), 2)
            items.append({"description": str(desc).strip(), "quantity": qty, "unit_price": unit, "total": round(qty * unit, 2)})
        except (TypeError, ValueError):
            continue
    return items


def generate_records(
    schema: dict[str, Any],
    n: int,
    seed: Optional[int] = None,
) -> Optional[tuple[list[dict[str, Any]], dict[str, Any]]]:
    """Generate `n` records via real NeMo Data Designer.

    Returns (records, report) on success, or None when the real path is not
    available/failed (caller falls back to the in-app synthesizer).
    """
    try:
        builder, post_process = build_builder(schema)
        DataDesigner = _dd()[0]
        designer = DataDesigner()
        rng = synthesizer.random.Random(seed) if seed is not None else synthesizer.random.Random()
        results = designer.preview(builder, num_records=n)
        rows = results.dataset.to_dict("records")
        records = [post_process(row, rng) for row in rows]
        records = [r for r in records if r]
        report = {
            "provider": "nemo-data-designer",
            "model": _model_name(),
            "requested": n,
            "generated": len(records),
            "columns": list(results.dataset.columns),
        }
        return records, report
    except Exception as exc:
        report = {"provider": "nemo-data-designer", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return None, report
