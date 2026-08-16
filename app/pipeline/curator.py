"""NeMo-Curator-style curation with QROTAID (Quality Retrieval, Organization,
Transformation, Augmentation, Integration, Deduplication) for seed records.

Enhanced pipeline:
1. Q - Quality Retrieval: Fetch real-world examples from web (web_retriever)
2. R - Ranking: Score and rank retrieved examples by relevance
3. O - Organization: Structure into canonical document schema
4. T - Transformation: Normalize, clean, extract structured fields
5. A - Augmentation: Enrich with domain vocabulary, standards
6. I - Integration: Merge with user seed data (HuggingFace/sample/empty)
7. D - Deduplication: Exact, near-dup, and semantic dedup

Returns curated records + comprehensive stage report."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from .web_retriever import retrieve_web_examples


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s-]?){9,14}\d(?!\d)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CURRENCY_RE = re.compile(r"[$€£¥₹]\s?\d+[.,]?\d*")
DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b", re.IGNORECASE)


def _normalize(value: Any) -> Any:
    """Unicode/whitespace normalization."""
    if isinstance(value, str):
        value = unicodedata.normalize("NFKC", value)
        value = re.sub(r"[ \t]+", " ", value).strip()
    elif isinstance(value, dict):
        value = {k: _normalize(v) for k, v in value.items()}
    elif isinstance(value, list):
        value = [_normalize(v) for v in value]
    return value


def _scrub_pii(value: Any) -> Any:
    """PII scrubbing for emails, phones, SSNs."""
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
    """Generate fingerprint for deduplication."""
    text = json.dumps(record, sort_keys=True, default=str).lower()
    if loose:
        text = re.sub(r"[^a-z0-9]", "", text)
    return hashlib.sha256(text.encode()).hexdigest()


def _semantic_fingerprint(record: dict, key_fields: list[str]) -> str:
    """Semantic fingerprint based on key business fields."""
    parts = []
    for field in key_fields:
        val = record.get(field)
        if val:
            parts.append(str(val).lower().strip())
    text = "|".join(parts)
    return hashlib.sha256(text.encode()).hexdigest()


def _extract_structured_fields(raw: dict, doc_type: str) -> dict[str, Any]:
    """Extract and structure fields from raw retrieved data."""
    structured = {}
    
    # Common field mappings
    field_mappings = {
        "invoice": {
            "vendor_name": ["vendor", "seller", "company", "business_name", "from"],
            "vendor_address": ["vendor_address", "seller_address", "company_address", "address"],
            "customer_name": ["customer", "buyer", "client", "bill_to", "to"],
            "customer_address": ["customer_address", "buyer_address", "client_address", "ship_to"],
            "invoice_number": ["invoice_number", "invoice_no", "inv_no", "number", "id"],
            "invoice_date": ["invoice_date", "date", "issued_date", "bill_date"],
            "due_date": ["due_date", "due", "payment_due", "payment_date"],
            "items": ["items", "line_items", "products", "services", "description"],
            "subtotal": ["subtotal", "sub_total", "net_amount", "amount_before_tax"],
            "tax_rate": ["tax_rate", "tax_percent", "gst_rate", "vat_rate"],
            "tax": ["tax", "tax_amount", "gst", "vat", "tax_total"],
            "total": ["total", "grand_total", "amount_due", "total_amount", "balance_due"],
            "payment_terms": ["payment_terms", "terms", "payment_conditions", "net_terms"],
        },
        "receipt": {
            "store_name": ["store", "merchant", "business", "shop", "vendor"],
            "store_address": ["address", "location", "store_address"],
            "receipt_number": ["receipt_number", "receipt_no", "transaction_id", "order_number"],
            "date": ["date", "transaction_date", "purchase_date"],
            "time": ["time", "transaction_time"],
            "cashier": ["cashier", "clerk", "employee", "staff"],
            "items": ["items", "products", "purchases", "line_items"],
            "subtotal": ["subtotal", "sub_total", "net"],
            "tax": ["tax", "tax_amount", "sales_tax"],
            "total": ["total", "grand_total", "amount_paid", "total_paid"],
            "payment_method": ["payment_method", "payment_type", "method", "paid_by"],
            "card_last4": ["card_last4", "last4", "card_ending", "card_number"],
        },
        "letter": {
            "sender_name": ["sender", "from_name", "author", "writer"],
            "sender_address": ["sender_address", "from_address", "return_address"],
            "recipient_name": ["recipient", "to_name", "addressee"],
            "recipient_address": ["recipient_address", "to_address", "address"],
            "date": ["date", "letter_date", "written_date"],
            "subject": ["subject", "re", "reference", "topic"],
            "salutation": ["salutation", "greeting", "dear"],
            "body": ["body", "content", "message", "text"],
            "closing": ["closing", "sign_off", "regards"],
        },
        "form": {
            "form_title": ["form_title", "title", "form_name", "application_type"],
            "organization": ["organization", "company", "institution", "agency"],
            "applicant_name": ["applicant_name", "name", "full_name", "applicant"],
            "date_of_birth": ["date_of_birth", "dob", "birth_date", "birthday"],
            "address": ["address", "residence", "home_address"],
            "phone": ["phone", "telephone", "mobile", "contact_number"],
            "email": ["email", "email_address", "e_mail"],
            "reference_number": ["reference_number", "ref_no", "application_number", "id"],
            "submission_date": ["submission_date", "date_submitted", "date"],
            "declaration": ["declaration", "statement", "affirmation", "certification"],
        },
    }
    
    mappings = field_mappings.get(doc_type, {})
    
    for target_field, source_keys in mappings.items():
        for key in source_keys:
            # Try exact match
            if key in raw:
                structured[target_field] = raw[key]
                break
            # Try case-insensitive match
            for raw_key, raw_val in raw.items():
                if raw_key.lower() == key.lower():
                    structured[target_field] = raw_val
                    break
            if target_field in structured:
                break
    
    return structured


def _rank_examples(examples: list, prompt: str, doc_type: str) -> list:
    """Rank retrieved examples by relevance to prompt and completeness."""
    prompt_terms = set(re.findall(r'\b\w+\b', prompt.lower()))
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "from", "by", "about", "as", "is", "with", "sample", "data", "document", "generate", "create", "make"}
    prompt_terms = {t for t in prompt_terms if t not in stop_words and len(t) > 2}
    
    for ex in examples:
        score = 0.0
        # Text relevance
        text = (ex.title + " " + ex.snippet).lower()
        for term in prompt_terms:
            if term in text:
                score += 1.0
        # Data completeness
        if ex.raw_data:
            score += len(ex.raw_data) * 0.5
        # Source quality
        if ex.source_url:
            score += 0.5
        ex.relevance_score = score
    
    return sorted(examples, key=lambda e: e.relevance_score, reverse=True)


def _organize_into_records(
    examples: list,
    doc_type: str,
) -> list[dict[str, Any]]:
    """Transform retrieved examples into structured records."""
    records = []
    for ex in examples:
        # Start with extracted fields from web retrieval
        record = dict(ex.raw_data) if ex.raw_data else {}
        
        # Add structured fields
        structured = _extract_structured_fields(ex.raw_data, doc_type)
        record.update(structured)
        
        # Add metadata
        record["_source_url"] = ex.source_url
        record["_source_title"] = ex.title
        record["_relevance_score"] = ex.relevance_score
        
        records.append(record)
    
    return records


def _augment_with_domain_knowledge(
    records: list[dict[str, Any]],
    doc_type: str,
    prompt: str,
) -> list[dict[str, Any]]:
    """Augment records with domain-specific vocabulary and standards."""
    # Extract domain terms from prompt
    domain_terms = set(re.findall(r'\b\w+\b', prompt.lower()))
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "from", "by", "about", "as", "is", "with", "sample", "data", "document", "generate", "create", "make", "invoice", "receipt", "letter", "form"}
    domain_terms = {t for t in domain_terms if t not in stop_words and len(t) > 2}
    
    # Add domain vocabulary to each record
    for record in records:
        if "item_vocabulary" not in record:
            record["item_vocabulary"] = list(domain_terms)[:15]
        record["_domain_terms"] = list(domain_terms)
    
    return records


def _deduplicate(
    records: list[dict[str, Any]],
    doc_type: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Multi-stage deduplication: exact, near, semantic."""
    report = {"input_records": len(records)}
    if not records:
        report["note"] = "no records to deduplicate"
        return [], report
    
    # Stage 1: Normalize
    normalized = [_normalize(r) for r in records]
    report["after_normalization"] = len(normalized)
    
    # Stage 2: Exact deduplication
    seen_exact = set()
    exact_deduped = []
    for r in normalized:
        fp = _fingerprint(r)
        if fp not in seen_exact:
            seen_exact.add(fp)
            exact_deduped.append(r)
    report["after_exact_dedup"] = len(exact_deduped)
    
    # Stage 3: Near deduplication (loose fingerprint)
    seen_loose = set()
    near_deduped = []
    for r in exact_deduped:
        fp = _fingerprint(r, loose=True)
        if fp not in seen_loose:
            seen_loose.add(fp)
            near_deduped.append(r)
    report["after_near_dedup"] = len(near_deduped)
    
    # Stage 4: Semantic deduplication (key business fields)
    key_fields = {
        "invoice": ["vendor_name", "invoice_number", "total"],
        "receipt": ["store_name", "receipt_number", "total"],
        "letter": ["sender_name", "recipient_name", "date"],
        "form": ["organization", "applicant_name", "reference_number"],
    }.get(doc_type, ["name", "id", "total"])
    
    seen_semantic = set()
    semantic_deduped = []
    for r in near_deduped:
        fp = _semantic_fingerprint(r, key_fields)
        if fp not in seen_semantic:
            seen_semantic.add(fp)
            semantic_deduped.append(r)
    report["after_semantic_dedup"] = len(semantic_deduped)
    
    # Stage 5: Quality filter
    filtered = [
        r for r in semantic_deduped
        if len(json.dumps(r, default=str)) >= 50 and any(v not in (None, "", [], {}) for v in r.values())
    ]
    report["after_quality_filter"] = len(filtered)
    
    # Stage 6: PII scrubbing
    scrubbed = [_scrub_pii(r) for r in filtered]
    report["pii_scrubbed"] = True
    report["output_records"] = len(scrubbed)
    
    return scrubbed, report


def curate(
    seed_records: list[dict[str, Any]],
    prompt: str = "",
    doc_type: str = "invoice",
    use_web_retrieval: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Enhanced NeMo Curator with QROTAID pipeline.
    
    Args:
        seed_records: User-provided seed data (HuggingFace/sample/empty)
        prompt: User's prompt describing desired documents
        doc_type: Document type (invoice, receipt, letter, form)
        use_web_retrieval: Whether to fetch real-world examples from web
    
    Returns:
        (curated_records, stage_report)
    """
    report: dict[str, Any] = {"qrotaid_stages": {}}
    
    # Q - Quality Retrieval: Fetch real-world examples from web
    web_examples = []
    if use_web_retrieval and prompt:
        try:
            web_examples = retrieve_web_examples(prompt, doc_type, max_examples=15)
            report["qrotaid_stages"]["quality_retrieval"] = {
                "examples_found": len(web_examples),
                "sources": list(set(e.source_url for e in web_examples if e.source_url)),
            }
        except Exception as e:
            report["qrotaid_stages"]["quality_retrieval"] = {"error": str(e)[:200]}
    else:
        report["qrotaid_stages"]["quality_retrieval"] = {"skipped": True, "reason": "no prompt or disabled"}
    
    # R - Ranking: Score and rank retrieved examples
    ranked_examples = _rank_examples(web_examples, prompt, doc_type)
    report["qrotaid_stages"]["ranking"] = {
        "top_scores": [e.relevance_score for e in ranked_examples[:5]],
    }
    
    # O - Organization: Structure into canonical schema
    organized_records = _organize_into_records(ranked_examples, doc_type)
    report["qrotaid_stages"]["organization"] = {
        "records_created": len(organized_records),
    }
    
    # Combine with user seed records (seed records take priority for user intent)
    all_records = seed_records + organized_records
    report["qrotaid_stages"]["integration"] = {
        "seed_records": len(seed_records),
        "web_records": len(organized_records),
        "total_before_dedup": len(all_records),
    }
    
    # T - Transformation + A - Augmentation + I - Integration already done
    augmented = _augment_with_domain_knowledge(all_records, doc_type, prompt)
    report["qrotaid_stages"]["augmentation"] = {
        "domain_terms_extracted": len(set().union(*[r.get("_domain_terms", []) for r in augmented])) if augmented else 0,
    }
    
    # D - Deduplication (multi-stage)
    curated, dedup_report = _deduplicate(augmented, doc_type)
    report["qrotaid_stages"]["deduplication"] = dedup_report
    
    return curated, report


def seed_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compact summary of the curated seed corpus for the Data Designer."""
    if not records:
        return {"count": 0, "columns": []}
    columns: dict[str, str] = {}
    for r in records[:30]:
        for k, v in r.items():
            if k.startswith("_"):  # Skip internal fields
                continue
            columns.setdefault(k, type(v).__name__)
    return {
        "count": len(records),
        "columns": [{"name": k, "type": t} for k, t in list(columns.items())[:40]],
        "example": records[0] if records else {},
    }


# ---- Local testing ----
if __name__ == "__main__":
    # Test with a software invoice prompt
    seed = []  # Empty seed
    prompt = "software SaaS invoices with subscription billing, monthly recurring revenue"
    doc_type = "invoice"
    
    curated, report = curate(seed, prompt, doc_type, use_web_retrieval=True)
    print(json.dumps(report, indent=2, default=str))
    print(f"\nCurated {len(curated)} records")
    for i, r in enumerate(curated[:2]):
        print(f"\nRecord {i}:")
        for k, v in r.items():
            if not k.startswith("_"):
                print(f"  {k}: {v}")