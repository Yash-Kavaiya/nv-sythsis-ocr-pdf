"""NeMo-Data-Designer-style stage: turn one prompt (+ curated seed stats + real examples)
into a document schema that drives synthesis, LaTeX layout and evaluation."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from .llm import LLMClient, extract_json, ensure_json_object

DOC_TYPE_KEYWORDS = {
    "invoice": ["invoice", "bill", "billing", "gst", "tax invoice", "purchase order"],
    "receipt": ["receipt", "pos", "store", "shop", "grocery", "retail", "restaurant", "pharmacy", "cafe"],
    "letter": ["letter", "correspondence", "memo", "notice", "cover letter"],
    "form": ["form", "application", "registration", "enrollment", "kyc", "survey", "prescription"],
}

BASE_FIELDS: dict[str, list[dict[str, str]]] = {
    "invoice": [
        {"name": "vendor_name", "type": "company"},
        {"name": "vendor_address", "type": "address"},
        {"name": "customer_name", "type": "name"},
        {"name": "customer_address", "type": "address"},
        {"name": "invoice_number", "type": "id"},
        {"name": "invoice_date", "type": "date"},
        {"name": "due_date", "type": "date"},
        {"name": "items", "type": "line_items"},
        {"name": "subtotal", "type": "money"},
        {"name": "tax_rate", "type": "percent"},
        {"name": "tax", "type": "money"},
        {"name": "total", "type": "money"},
        {"name": "payment_terms", "type": "choice:Net 15,Net 30,Net 45,Net 60,Due on receipt"},
    ],
    "receipt": [
        {"name": "store_name", "type": "company"},
        {"name": "store_address", "type": "address"},
        {"name": "receipt_number", "type": "id"},
        {"name": "date", "type": "date"},
        {"name": "time", "type": "time"},
        {"name": "cashier", "type": "name"},
        {"name": "items", "type": "line_items"},
        {"name": "subtotal", "type": "money"},
        {"name": "tax", "type": "money"},
        {"name": "total", "type": "money"},
        {"name": "payment_method", "type": "choice:CASH,VISA,MASTERCARD,UPI,DEBIT"},
        {"name": "card_last4", "type": "digits4"},
    ],
    "letter": [
        {"name": "sender_name", "type": "name"},
        {"name": "sender_address", "type": "address"},
        {"name": "recipient_name", "type": "name"},
        {"name": "recipient_address", "type": "address"},
        {"name": "date", "type": "date"},
        {"name": "subject", "type": "sentence"},
        {"name": "salutation", "type": "choice:Dear Sir or Madam,Dear Hiring Manager,To Whom It May Concern,Dear Committee"},
        {"name": "body", "type": "paragraphs"},
        {"name": "closing", "type": "choice:Sincerely,Yours faithfully,Best regards,Yours truly"},
    ],
    "form": [
        {"name": "form_title", "type": "choice:Membership Application Form,Registration Form,Service Request Form,Change of Address Form,Account Opening Form"},
        {"name": "organization", "type": "company"},
        {"name": "applicant_name", "type": "name"},
        {"name": "date_of_birth", "type": "dob"},
        {"name": "address", "type": "address"},
        {"name": "phone", "type": "phone"},
        {"name": "email", "type": "email"},
        {"name": "reference_number", "type": "id"},
        {"name": "submission_date", "type": "date"},
        {"name": "declaration", "type": "choice:I hereby declare that the information provided above is true and correct to the best of my knowledge,I certify that all details furnished in this form are accurate and complete,I confirm that the particulars given herein are true and I agree to the terms of service"},
    ],
}

# Enhanced system prompt that uses real curated examples
DESIGN_SYSTEM_PROMPT = """You are NeMo Data Designer, an expert at designing synthetic document datasets \
for OCR training. Given a user prompt, curated seed statistics, AND real-world examples, \
output ONLY a JSON object:
{
  "doc_type": "invoice" | "receipt" | "letter" | "form",
  "theme": "<short description of business domain / locale / style>",
  "company_style": "<kind of organizations to use>",
  "item_vocabulary": ["<8-15 realistic product/service names fitting the theme>"],
  "locale": "<faker locale like en_US, en_IN, de_DE>",
  "currency": "<currency symbol>",
  "field_overrides": {"<field_name>": {"type": "<type>", "pattern": "<regex>", "examples": [...]}} optional
}
The real-world examples contain actual field values from real documents. Use them to:
- Extract realistic company/vendor names, product/service names
- Determine the correct locale and currency
- Identify domain-specific terminology and patterns
- Customize field types with real patterns/examples"""


def infer_doc_type(prompt: str) -> str:
    p = prompt.lower()
    scores = {
        dt: sum(1 for kw in kws if kw in p)
        for dt, kws in DOC_TYPE_KEYWORDS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "invoice"


def _analyze_curated_records(
    curated_records: list[dict[str, Any]],
    doc_type: str,
) -> dict[str, Any]:
    """Analyze curated records to extract domain-specific patterns."""
    analysis = {
        "company_names": [],
        "item_descriptions": [],
        "addresses": [],
        "currencies": [],
        "locales": [],
        "tax_rates": [],
        "payment_terms": [],
        "payment_methods": [],
        "field_patterns": {},
    }
    
    for record in curated_records:
        # Skip internal fields
        clean_record = {k: v for k, v in record.items() if not k.startswith("_")}
        
        # Collect company/organization names
        for key in ["vendor_name", "store_name", "sender_name", "organization", "company", "business"]:
            if key in clean_record and clean_record[key]:
                analysis["company_names"].append(str(clean_record[key]))
        
        # Collect item descriptions
        items = clean_record.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    desc = item.get("description") or item.get("name") or item.get("product")
                    if desc:
                        analysis["item_descriptions"].append(str(desc))
        
        # Collect addresses
        for key in ["vendor_address", "store_address", "customer_address", "address", "sender_address", "recipient_address"]:
            if key in clean_record and clean_record[key]:
                analysis["addresses"].append(str(clean_record[key]))
        
        # Detect currency from money fields
        for key in ["total", "subtotal", "tax", "unit_price", "amount"]:
            if key in clean_record and clean_record[key]:
                val = str(clean_record[key])
                currency_match = re.search(r"[$€£¥₹]", val)
                if currency_match:
                    analysis["currencies"].append(currency_match.group())
        
        # Collect tax rates
        for key in ["tax_rate", "gst_rate", "vat_rate"]:
            if key in clean_record and clean_record[key]:
                try:
                    analysis["tax_rates"].append(float(clean_record[key]))
                except (ValueError, TypeError):
                    pass
        
        # Collect payment terms
        for key in ["payment_terms", "terms"]:
            if key in clean_record and clean_record[key]:
                analysis["payment_terms"].append(str(clean_record[key]))
        
        # Collect payment methods
        for key in ["payment_method", "method", "paid_by"]:
            if key in clean_record and clean_record[key]:
                analysis["payment_methods"].append(str(clean_record[key]))
        
        # Detect locale from addresses (country, state patterns)
        for addr in analysis["addresses"][-1:]:
            if re.search(r"\b(India|IN|INR|₹)\b", addr, re.IGNORECASE):
                analysis["locales"].append("en_IN")
            elif re.search(r"\b(Germany|DE|EUR|€)\b", addr, re.IGNORECASE):
                analysis["locales"].append("de_DE")
            elif re.search(r"\b(UK|GB|GBP|£)\b", addr, re.IGNORECASE):
                analysis["locales"].append("en_GB")
            elif re.search(r"\b(US|USA|USD|\$)\b", addr, re.IGNORECASE):
                analysis["locales"].append("en_US")
    
    # Deduplicate and get most common
    for key in ["company_names", "item_descriptions", "addresses", "currencies", "locales", "tax_rates", "payment_terms", "payment_methods"]:
        if analysis[key]:
            counter = Counter(analysis[key])
            analysis[key] = [item for item, _ in counter.most_common(10)]
    
    return analysis


def _build_field_overrides(
    analysis: dict[str, Any],
    doc_type: str,
) -> dict[str, Any]:
    """Build field type overrides based on real data patterns."""
    overrides = {}
    
    # Currency override
    if analysis["currencies"]:
        currency = Counter(analysis["currencies"]).most_common(1)[0][0]
        overrides["currency"] = {"detected": currency}
    
    # Locale override
    if analysis["locales"]:
        locale = Counter(analysis["locales"]).most_common(1)[0][0]
        overrides["locale"] = {"detected": locale}
    
    # Tax rate patterns
    if analysis["tax_rates"]:
        rates = sorted(set(round(r, 1) for r in analysis["tax_rates"]))
        overrides["tax_rate"] = {"type": "percent", "common_values": rates}
    
    # Payment terms from real data
    if analysis["payment_terms"]:
        terms = list(set(analysis["payment_terms"]))
        if terms:
            overrides["payment_terms"] = {"type": "choice:" + ",".join(terms[:8])}
    
    # Payment methods from real data
    if analysis["payment_methods"]:
        methods = list(set(analysis["payment_methods"]))
        if methods:
            overrides["payment_method"] = {"type": "choice:" + ",".join(methods[:8])}
    
    return overrides


def design_schema(
    prompt: str,
    seed_stats: dict[str, Any],
    llm: LLMClient,
    doc_type_override: Optional[str] = None,
    curated_records: Optional[list[dict[str, Any]]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (schema, stage_report)."""
    report: dict[str, Any] = {"llm_backed": False}
    design: dict[str, Any] = {}
    
    # Analyze curated records for domain-specific patterns
    curated_analysis = {}
    field_overrides = {}
    if curated_records:
        curated_analysis = _analyze_curated_records(curated_records, doc_type_override or infer_doc_type(prompt))
        field_overrides = _build_field_overrides(curated_analysis, doc_type_override or infer_doc_type(prompt))
        report["curated_analysis"] = {
            "unique_companies": len(curated_analysis.get("company_names", [])),
            "unique_items": len(curated_analysis.get("item_descriptions", [])),
            "detected_currency": field_overrides.get("currency", {}).get("detected"),
            "detected_locale": field_overrides.get("locale", {}).get("detected"),
            "common_tax_rates": field_overrides.get("tax_rate", {}).get("common_values", []),
        }
    
    if llm.available:
        try:
            user_msg = f"User prompt: {prompt}\n"
            if seed_stats.get("count"):
                user_msg += f"\nSeed corpus stats: {seed_stats}\n"
            if curated_analysis:
                user_msg += f"\nReal-world curated examples analysis:\n"
                user_msg += f"  Company names: {curated_analysis.get('company_names', [])[:5]}\n"
                user_msg += f"  Item descriptions: {curated_analysis.get('item_descriptions', [])[:10]}\n"
                user_msg += f"  Addresses: {curated_analysis.get('addresses', [])[:3]}\n"
                user_msg += f"  Detected currency: {field_overrides.get('currency', {}).get('detected', 'unknown')}\n"
                user_msg += f"  Detected locale: {field_overrides.get('locale', {}).get('detected', 'unknown')}\n"
                user_msg += f"  Common tax rates: {field_overrides.get('tax_rate', {}).get('common_values', [])}\n"
                user_msg += f"  Payment terms: {curated_analysis.get('payment_terms', [])}\n"
                user_msg += f"  Payment methods: {curated_analysis.get('payment_methods', [])}\n"
            
            raw = llm.chat(
                [
                    {"role": "system", "content": DESIGN_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.4,
            )
            design = ensure_json_object(raw)
            report["llm_backed"] = True
        except Exception as exc:  # fall back below
            report["llm_error"] = str(exc)[:300]
    
    doc_type = doc_type_override or design.get("doc_type") or infer_doc_type(prompt)
    if doc_type not in BASE_FIELDS:
        doc_type = "invoice"
    
    # Apply field overrides from curated analysis
    fields = BASE_FIELDS[doc_type].copy()
    if field_overrides:
        for field in fields:
            fname = field["name"]
            if fname in field_overrides:
                override = field_overrides[fname]
                if "type" in override:
                    field["type"] = override["type"]
                if "pattern" in override:
                    field["pattern"] = override["pattern"]
                if "examples" in override:
                    field["examples"] = override["examples"]
    
    # Use curated data for theme, vocabulary, locale, currency
    theme = design.get("theme") or prompt.strip()
    if curated_records and not design.get("theme"):
        # Build theme from real data
        companies = curated_analysis.get("company_names", [])
        items = curated_analysis.get("item_descriptions", [])
        if companies or items:
            theme = f"{prompt.strip()} (based on real examples: {', '.join(companies[:3])})"
    
    item_vocabulary = design.get("item_vocabulary", [])
    if curated_records and not item_vocabulary:
        item_vocabulary = curated_analysis.get("item_descriptions", [])[:15]
    
    locale = design.get("locale", "en_US")
    if curated_records and field_overrides.get("locale", {}).get("detected"):
        locale = field_overrides["locale"]["detected"]
    
    currency = design.get("currency", "$")
    if curated_records and field_overrides.get("currency", {}).get("detected"):
        currency = field_overrides["currency"]["detected"]
    
    schema = {
        "doc_type": doc_type,
        "theme": theme,
        "company_style": design.get("company_style", ""),
        "item_vocabulary": item_vocabulary,
        "locale": locale,
        "currency": currency,
        "fields": fields,
        "seed_stats": seed_stats,
        "curated_analysis": curated_analysis,
        "field_overrides": field_overrides,
    }
    report.update({
        "doc_type": doc_type,
        "field_count": len(schema["fields"]),
        "theme": schema["theme"],
        "locale": schema["locale"],
        "currency": schema["currency"],
        "item_vocabulary_size": len(schema["item_vocabulary"]),
    })
    return schema, report