"""Pure-Python PDF renderer (fpdf2) used when no LaTeX engine is installed.

Mirrors the layout of the LaTeX templates closely enough that the PDF and the
.tex source describe the same document, keeping ground truth consistent.
"""
from __future__ import annotations

from typing import Any

from fpdf import FPDF


def _s(value: Any) -> str:
    text = str(value if value is not None else "")
    # Core fonts are latin-1 only; degrade gracefully.
    return text.encode("latin-1", "replace").decode("latin-1")


def _money(value: Any, currency: str) -> str:
    try:
        return f"{_s(currency)}{float(value):,.2f}"
    except (TypeError, ValueError):
        return f"{_s(currency)}{_s(value)}"


def _items_of(record: dict) -> list[dict]:
    items = record.get("items")
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


def render_invoice(record: dict[str, Any], currency: str, path: str) -> None:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 26)
    pdf.cell(120, 12, "INVOICE")
    pdf.set_font("helvetica", "", 13)
    pdf.cell(0, 12, _s(record.get("invoice_number", "")), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_draw_color(60, 60, 60)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(5)

    y0 = pdf.get_y()
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(90, 6, "From", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(90, 5, _s(record.get("vendor_name", "")) + "\n" + _s(record.get("vendor_address", "")))
    y_left = pdf.get_y()
    pdf.set_xy(110, y0)
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(90, 6, "Bill To")
    pdf.set_xy(110, y0 + 6)
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(88, 5, _s(record.get("customer_name", "")) + "\n" + _s(record.get("customer_address", "")))
    pdf.set_y(max(y_left, pdf.get_y()) + 6)

    pdf.set_font("helvetica", "B", 10)
    pdf.cell(95, 6, f"Invoice Date: {_s(record.get('invoice_date', ''))}")
    pdf.cell(0, 6, f"Due Date: {_s(record.get('due_date', ''))}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_fill_color(235, 235, 235)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(88, 7, "Description", border=1, fill=True)
    pdf.cell(20, 7, "Qty", border=1, fill=True, align="R")
    pdf.cell(38, 7, "Unit Price", border=1, fill=True, align="R")
    pdf.cell(38, 7, "Amount", border=1, fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    for it in _items_of(record):
        pdf.cell(88, 7, _s(it.get("description", ""))[:52], border=1)
        pdf.cell(20, 7, _s(it.get("quantity", "")), border=1, align="R")
        pdf.cell(38, 7, _money(it.get("unit_price", 0), currency), border=1, align="R")
        pdf.cell(38, 7, _money(it.get("total", 0), currency), border=1, align="R",
                 new_x="LMARGIN", new_y="NEXT")

    for label, key, bold in (("Subtotal", "subtotal", False),
                             (f"Tax ({_s(record.get('tax_rate', ''))}%)", "tax", False),
                             ("Total", "total", True)):
        pdf.set_font("helvetica", "B" if bold else "", 10)
        pdf.cell(108, 7, "")
        pdf.cell(38, 7, label, border=1, align="R")
        pdf.cell(38, 7, _money(record.get(key, 0), currency), border=1, align="R",
                 new_x="LMARGIN", new_y="NEXT")

    pdf.ln(8)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(32, 6, "Payment Terms:")
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(0, 6, _s(record.get("payment_terms", "")))
    pdf.ln(10)
    pdf.set_text_color(120, 120, 120)
    pdf.set_font("helvetica", "I", 9)
    pdf.cell(0, 6, "Thank you for your business.")
    pdf.output(path)


def render_receipt(record: dict[str, Any], currency: str, path: str) -> None:
    pdf = FPDF(format=(90, 220))
    pdf.set_margins(8, 8)
    pdf.set_auto_page_break(True, margin=8)
    pdf.add_page()
    pdf.set_font("courier", "B", 12)
    pdf.cell(0, 6, _s(record.get("store_name", "")), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("courier", "", 7)
    pdf.multi_cell(0, 3.5, _s(record.get("store_address", "")), align="C",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 3, "-" * 40, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("courier", "", 8)
    pdf.cell(0, 4, f"Receipt: {_s(record.get('receipt_number', ''))}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 4, f"Date: {_s(record.get('date', ''))}  Time: {_s(record.get('time', ''))}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 4, f"Cashier: {_s(record.get('cashier', ''))}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 3, "-" * 40, align="C", new_x="LMARGIN", new_y="NEXT")
    for it in _items_of(record):
        pdf.cell(38, 4, _s(it.get("description", ""))[:21])
        pdf.cell(8, 4, _s(it.get("quantity", "")), align="R")
        pdf.cell(13, 4, _s(it.get("unit_price", "")), align="R")
        pdf.cell(0, 4, _s(it.get("total", "")), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 3, "-" * 40, align="C", new_x="LMARGIN", new_y="NEXT")
    for label, key, bold in (("SUBTOTAL", "subtotal", False), ("TAX", "tax", False), ("TOTAL", "total", True)):
        pdf.set_font("courier", "B" if bold else "", 8)
        pdf.cell(40, 4, label)
        pdf.cell(0, 4, _money(record.get(key, 0), currency), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("courier", "", 8)
    pdf.cell(0, 3, "-" * 40, align="C", new_x="LMARGIN", new_y="NEXT")
    last4 = _s(record.get("card_last4", ""))
    paid = f"Paid: {_s(record.get('payment_method', ''))}" + (f" ****{last4}" if last4 else "")
    pdf.cell(0, 4, paid, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.cell(0, 4, "*** THANK YOU ***", align="C")
    pdf.output(path)


def render_letter(record: dict[str, Any], currency: str, path: str) -> None:
    pdf = FPDF(format="A4")
    pdf.set_margins(25, 22)
    pdf.set_auto_page_break(True, margin=22)
    pdf.add_page()
    pdf.set_font("times", "", 11)
    pdf.multi_cell(0, 5.5, _s(record.get("sender_name", "")) + "\n" + _s(record.get("sender_address", "")))
    pdf.ln(4)
    pdf.cell(0, 6, _s(record.get("date", "")), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.multi_cell(0, 5.5, _s(record.get("recipient_name", "")) + "\n" + _s(record.get("recipient_address", "")))
    pdf.ln(6)
    pdf.set_font("times", "B", 11)
    pdf.multi_cell(0, 6, f"Subject: {_s(record.get('subject', ''))}")
    pdf.ln(3)
    pdf.set_font("times", "", 11)
    pdf.cell(0, 6, f"{_s(record.get('salutation', 'Dear Sir/Madam'))},", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.multi_cell(0, 6, _s(record.get("body", "")))
    pdf.ln(6)
    pdf.cell(0, 6, f"{_s(record.get('closing', 'Sincerely'))},", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.cell(0, 6, _s(record.get("sender_name", "")))
    pdf.output(path)


def render_form(record: dict[str, Any], currency: str, path: str) -> None:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()
    pdf.set_font("helvetica", "", 12)
    pdf.cell(0, 7, _s(record.get("organization", "")), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "B", 17)
    pdf.cell(0, 10, _s(record.get("form_title", "")), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 6, f"Reference No: {_s(record.get('reference_number', ''))}", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)
    rows = [
        ("Applicant Name", "applicant_name"),
        ("Date of Birth", "date_of_birth"),
        ("Address", "address"),
        ("Phone", "phone"),
        ("Email", "email"),
        ("Submission Date", "submission_date"),
    ]
    for label, key in rows:
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(55, 8, label, border="B")
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(0, 8, _s(record.get(key, "")), border="B", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(28, 6, "Declaration:")
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(0, 6, _s(record.get("declaration", "")) + ".")
    pdf.ln(16)
    pdf.cell(70, 6, "_" * 30)
    pdf.cell(0, 6, "_" * 30, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 9)
    pdf.cell(70, 5, "Signature of Applicant")
    pdf.cell(0, 5, "For Office Use Only")
    pdf.output(path)


RENDERERS = {
    "invoice": render_invoice,
    "receipt": render_receipt,
    "letter": render_letter,
    "form": render_form,
}


def render_pdf(doc_type: str, record: dict[str, Any], currency: str, path: str) -> None:
    RENDERERS[doc_type](record, currency, path)
