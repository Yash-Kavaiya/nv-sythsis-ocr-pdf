"""Provider resolution + gating tests (offline — no network, no keys)."""
import pytest

from app.pipeline import data_designer_provider, nemo_curator_provider, providers, safe_synthesizer_provider


def test_resolve_defaults_to_inapp():
    # conftest clears NVIDIA_API_KEY, so the real paths must not claim availability.
    for stage in providers.STAGES:
        res = providers.resolve(stage)
        assert res["provider"] == "inapp", f"{stage} should be inapp: {res}"


def test_resolve_explicit_inapp_never_uses_nemo(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    for stage in providers.STAGES:
        assert providers.resolve(stage, "inapp")["provider"] == "inapp"


def test_resolve_nemo_requires_package_and_key(monkeypatch):
    # Key set but package importable -> nemo for designer/synthesizer.
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    for stage in ("designer", "synthesizer"):
        res = providers.resolve(stage, "nemo")
        # data-designer IS installed in this venv, so nemo should resolve.
        assert res["provider"] == "nemo", res
    # Curator never resolves nemo without the explicit env flag.
    assert providers.resolve("curator", "nemo")["provider"] == "inapp"


def test_curator_nemo_requires_flag(monkeypatch):
    monkeypatch.setenv("NEMO_CURATOR", "1")
    # Without the package importable (Linux-only), still inapp.
    assert providers.resolve("curator", "nemo")["provider"] == "inapp"


def test_nemo_curator_provider_unavailable_offline():
    assert nemo_curator_provider.available() is False
    with pytest.raises(RuntimeError, match="NEMO_CURATOR=1"):
        nemo_curator_provider.curate_seed([])


def test_safe_synthesizer_privacy_report_counts_pii():
    records = [
        {"vendor_name": "Acme", "contact": "jane@example.com", "phone": "+91 98765 43210"},
        {"vendor_name": "Globex", "contact": "bob@example.org", "phone": "555-0100"},
    ]
    report = safe_synthesizer_provider.privacy_report(records)
    assert report["records"] == 2
    assert report["pii_emails_found"] == 2
    assert report["pii_phones_found"] >= 1
    assert report["pii_scrubbed"] is True


def test_data_designer_build_builder_offline():
    """Column translation must not require a key or network."""
    schema = {
        "doc_type": "invoice",
        "theme": "test invoices",
        "currency": "$",
        "item_vocabulary": ["Widget", "Gadget"],
        "fields": [
            {"name": "vendor_name", "type": "company"},
            {"name": "invoice_number", "type": "id"},
            {"name": "invoice_date", "type": "date"},
            {"name": "items", "type": "line_items"},
            {"name": "tax_rate", "type": "percent"},
            {"name": "payment_terms", "type": "choice:Net 15,Net 30"},
        ],
    }
    builder, post = data_designer_provider.build_builder(schema)
    names = {getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None)
             for c in builder.get_column_configs()}
    assert {"vendor_name", "invoice_number", "items", "tax_rate", "payment_terms"} <= names

    # post_process maps a generated row into a canonical, consistent record.
    row = {
        "vendor_name": "Acme Supplies",
        "invoice_number": "ABCDE12345",
        "invoice_date": "2025-03-01",
        "items": '[{"description": "Widget", "quantity": 2, "unit_price": 10.5, "total": 21.0}]',
        "tax_rate": 10.0,
        "payment_terms": "Net 30",
        "subtotal": 999.0,  # will be recomputed
        "tax": 1.0,  # will be recomputed
        "total": 1.0,  # will be recomputed
    }
    import random

    record = post(row, random.Random(1))
    assert record["invoice_number"].startswith("AB")
    assert record["invoice_date"] == "01 Mar 2025"
    assert record["subtotal"] == 21.0
    assert record["tax"] == 2.1
    assert record["total"] == 23.1
    assert record["items"][0]["total"] == 21.0


def test_data_designer_generate_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    schema = {
        "doc_type": "invoice",
        "theme": "t",
        "currency": "$",
        "fields": [{"name": "vendor_name", "type": "company"}],
    }
    records, report = data_designer_provider.generate_records(schema, 2)
    assert records is None
    assert "error" in report
