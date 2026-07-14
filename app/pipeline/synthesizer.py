"""NeMo-Synthesizer-style stage: generate ground-truth JSON records from the
designed schema. Uses the NVIDIA LLM when available for themed values; always
enforces arithmetic consistency so ground truth is exact for OCR evals."""
from __future__ import annotations

import random
from typing import Any, Optional

from faker import Faker

from .llm import LLMClient, extract_json

SYNTH_SYSTEM_PROMPT = """You are NeMo Synthesizer. Generate realistic synthetic document records for OCR \
training. Output ONLY a JSON array of {n} objects. Each object must contain exactly these keys: {keys}. \
"items" (when present) is an array of 2-6 objects with keys: description, quantity, unit_price, total. \
Numbers must be plain numbers (no currency symbols). Dates formatted like "12 Mar 2025". \
Theme: {theme}. Use varied, realistic values - no placeholders."""


def _faker_for(schema: dict[str, Any]) -> Faker:
    try:
        return Faker(schema.get("locale") or "en_US")
    except AttributeError:
        return Faker("en_US")


def _gen_items(fake: Faker, vocab: list[str], rng: random.Random) -> list[dict[str, Any]]:
    n = rng.randint(2, 6)
    items = []
    for _ in range(n):
        desc = rng.choice(vocab) if vocab else " ".join(fake.words(nb=rng.randint(2, 4))).title()
        qty = rng.randint(1, 12)
        unit = round(rng.uniform(1.5, 480.0), 2)
        items.append({
            "description": desc,
            "quantity": qty,
            "unit_price": unit,
            "total": round(qty * unit, 2),
        })
    return items


def _gen_field(ftype: str, fake: Faker, rng: random.Random, vocab: list[str]) -> Any:
    if ftype == "company":
        return fake.company()
    if ftype == "name":
        return fake.name()
    if ftype == "address":
        return fake.address().replace("\n", ", ")
    if ftype == "id":
        return f"{rng.choice('ABCDEFGHJKMNP')}{rng.choice('QRSTUVWXYZ')}-{rng.randint(10000, 99999)}"
    if ftype == "dob":
        return fake.date_of_birth(minimum_age=18, maximum_age=80).strftime("%d %b %Y")
    if ftype == "date":
        return fake.date_between(start_date="-2y", end_date="+60d").strftime("%d %b %Y")
    if ftype == "time":
        return f"{rng.randint(8, 21):02d}:{rng.randint(0, 59):02d}"
    if ftype == "money":
        return round(rng.uniform(10, 5000), 2)
    if ftype == "percent":
        return rng.choice([5.0, 8.0, 10.0, 12.0, 18.0])
    if ftype == "line_items":
        return _gen_items(fake, vocab, rng)
    if ftype.startswith("choice:"):
        return rng.choice(ftype.split(":", 1)[1].split(","))
    if ftype == "digits4":
        return f"{rng.randint(0, 9999):04d}"
    if ftype == "phone":
        return fake.phone_number()
    if ftype == "email":
        return fake.email()
    if ftype == "sentence":
        return fake.sentence(nb_words=6).rstrip(".")
    if ftype == "paragraphs":
        return "\n\n".join(fake.paragraph(nb_sentences=rng.randint(3, 5)) for _ in range(rng.randint(2, 3)))
    return fake.word()


def _enforce_consistency(record: dict[str, Any], doc_type: str) -> dict[str, Any]:
    """Recompute derived money fields so ground truth is arithmetically exact."""
    if str(record.get("payment_method", "")).upper() in ("CASH", "UPI"):
        record["card_last4"] = ""
    items = record.get("items")
    if isinstance(items, list) and items:
        for it in items:
            if isinstance(it, dict):
                try:
                    qty = float(it.get("quantity", 1) or 1)
                    unit = float(it.get("unit_price", 0) or 0)
                    it["quantity"] = int(qty) if qty == int(qty) else qty
                    it["unit_price"] = round(unit, 2)
                    it["total"] = round(qty * unit, 2)
                except (TypeError, ValueError):
                    continue
        try:
            subtotal = round(sum(float(it.get("total", 0) or 0) for it in items if isinstance(it, dict)), 2)
            record["subtotal"] = subtotal
            if doc_type == "invoice":
                rate = float(record.get("tax_rate", 10) or 10)
                record["tax_rate"] = rate
                record["tax"] = round(subtotal * rate / 100, 2)
            else:
                record["tax"] = round(float(record.get("tax", subtotal * 0.08) or 0), 2)
                if record["tax"] > subtotal * 0.3:
                    record["tax"] = round(subtotal * 0.08, 2)
            record["total"] = round(subtotal + record["tax"], 2)
        except (TypeError, ValueError):
            pass
    return record


def _faker_record(schema: dict[str, Any], fake: Faker, rng: random.Random) -> dict[str, Any]:
    vocab = schema.get("item_vocabulary") or []
    record = {
        f["name"]: _gen_field(f["type"], fake, rng, vocab)
        for f in schema["fields"]
    }
    if "invoice_date" in record and "due_date" in record:
        from datetime import datetime, timedelta
        try:
            base = datetime.strptime(record["invoice_date"], "%d %b %Y")
            record["due_date"] = (base + timedelta(days=rng.choice([15, 30, 45, 60]))).strftime("%d %b %Y")
        except ValueError:
            pass
    if schema.get("company_style"):
        # Keep the themed flavor even in fallback mode.
        for key in ("vendor_name", "store_name", "organization"):
            if key in record:
                record[key] = f"{record[key].split(',')[0].split(' and ')[0]} {schema['company_style'].split(' ')[0].title()}".strip()
    return _enforce_consistency(record, schema["doc_type"])


def _valid_record(rec: Any, keys: list[str]) -> bool:
    return isinstance(rec, dict) and sum(1 for k in keys if k in rec and rec[k] not in (None, "")) >= max(3, int(len(keys) * 0.7))


def synthesize(
    schema: dict[str, Any],
    n: int,
    llm: LLMClient,
    seed: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Returns (records, stage_report)."""
    rng = random.Random(seed)
    fake = _faker_for(schema)
    if seed is not None:
        Faker.seed(seed)
    keys = [f["name"] for f in schema["fields"]]
    report: dict[str, Any] = {"requested": n, "llm_backed": False}
    records: list[dict[str, Any]] = []

    if llm.available:
        try:
            raw = llm.chat(
                [
                    {"role": "system", "content": SYNTH_SYSTEM_PROMPT.format(
                        n=n, keys=keys, theme=schema.get("theme", ""))},
                    {"role": "user", "content": f"Generate {n} {schema['doc_type']} records."},
                ],
                temperature=0.9,
                max_tokens=4096,
            )
            candidates = extract_json(raw)
            if isinstance(candidates, dict):
                candidates = [candidates]
            records = [
                _enforce_consistency(r, schema["doc_type"])
                for r in candidates if _valid_record(r, keys)
            ][:n]
            report["llm_backed"] = bool(records)
            report["llm_yield"] = len(records)
        except Exception as exc:
            report["llm_error"] = str(exc)[:300]

    while len(records) < n:
        records.append(_faker_record(schema, fake, rng))

    report["generated"] = len(records)
    report["faker_filled"] = report["generated"] - report.get("llm_yield", 0)
    return records, report
