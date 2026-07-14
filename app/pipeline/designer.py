"""NeMo-Data-Designer-style stage: turn one prompt (+ curated seed stats)
into a document schema that drives synthesis, LaTeX layout and evaluation."""
from __future__ import annotations

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

DESIGN_SYSTEM_PROMPT = """You are NeMo Data Designer, an expert at designing synthetic document datasets \
for OCR training. Given a user prompt and optional seed-corpus statistics, output ONLY a JSON object:
{
  "doc_type": "invoice" | "receipt" | "letter" | "form",
  "theme": "<short description of business domain / locale / style>",
  "company_style": "<kind of organizations to use>",
  "item_vocabulary": ["<8-15 realistic product/service names fitting the theme>"],
  "locale": "<faker locale like en_US, en_IN, de_DE>",
  "currency": "<currency symbol>"
}"""


def infer_doc_type(prompt: str) -> str:
    p = prompt.lower()
    scores = {
        dt: sum(1 for kw in kws if kw in p)
        for dt, kws in DOC_TYPE_KEYWORDS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "invoice"


def design_schema(
    prompt: str,
    seed_stats: dict[str, Any],
    llm: LLMClient,
    doc_type_override: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (schema, stage_report)."""
    report: dict[str, Any] = {"llm_backed": False}
    design: dict[str, Any] = {}

    if llm.available:
        try:
            user_msg = f"User prompt: {prompt}\n"
            if seed_stats.get("count"):
                user_msg += f"\nSeed corpus stats: {seed_stats}\n"
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

    schema = {
        "doc_type": doc_type,
        "theme": design.get("theme") or prompt.strip(),
        "company_style": design.get("company_style", ""),
        "item_vocabulary": design.get("item_vocabulary", []),
        "locale": design.get("locale", "en_US"),
        "currency": design.get("currency", "$"),
        "fields": BASE_FIELDS[doc_type],
        "seed_stats": seed_stats,
    }
    report.update({
        "doc_type": doc_type,
        "field_count": len(schema["fields"]),
        "theme": schema["theme"],
        "locale": schema["locale"],
    })
    return schema, report
