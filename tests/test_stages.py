# tests/test_stages.py
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Point DATA_DIR at tmp before importing app
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Re-import storage paths if module already cached — prefer patching app.storage.DATA_DIR
    import app.storage as storage
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(storage, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(storage, "EVALS_DIR", tmp_path / "evals")
    sample_path = tmp_path / "sample_seed.json"
    sample_path.write_text(
        '[{"text":"Invoice from Acme Corp for supplies","vendor":"Acme Corp","amount":45.99}]'
    )
    from app.pipeline import hf_loader
    monkeypatch.setattr(hf_loader, "SAMPLE_PATH", sample_path)
    from app.main import app
    return TestClient(app)


def test_create_run_writes_manifest(client, tmp_path):
    r = client.post("/api/runs", json={"prompt": "pharmacy invoices", "source_type": "empty"})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"].startswith("run_")
    assert (tmp_path / "runs" / body["run_id"] / "manifest.json").exists()
    assert body["stage_status"]["curator"] == "idle"


def test_curate_sample_writes_curated(client, tmp_path):
    run_id = client.post("/api/runs", json={"prompt": "x", "source_type": "sample"}).json()["run_id"]
    r = client.post(f"/api/runs/{run_id}/curate", json={"source_type": "sample"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["manifest"]["stage_status"]["curator"] == "done"
    curated = (tmp_path / "runs" / run_id / "curated.json").read_text()
    assert len(curated) > 2


def test_design_requires_curator(client):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    r = client.post(f"/api/runs/{run_id}/design", json={"prompt": "pharmacy invoices INR"})
    assert r.status_code in (400, 409)


def test_design_after_curate(client, tmp_path):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    r = client.post(f"/api/runs/{run_id}/design", json={"prompt": "pharmacy invoices in rupees"})
    assert r.status_code == 200
    assert r.json()["manifest"]["stage_status"]["designer"] == "done"
    assert (tmp_path / "runs" / run_id / "schema.json").exists()


def test_synthesize_requires_design(client):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    r = client.post(f"/api/runs/{run_id}/synthesize", json={"num_docs": 2, "seed": 1})
    assert r.status_code == 400
    body = r.json()
    assert body["stage"] == "synthesizer"


def test_synthesize_after_design(client, tmp_path):
    run_id = client.post("/api/runs", json={"prompt": "invoices"}).json()["run_id"]
    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    client.post(f"/api/runs/{run_id}/design", json={"prompt": "simple retail invoices USD"})
    r = client.post(f"/api/runs/{run_id}/synthesize", json={"num_docs": 2, "seed": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["stage_status"]["synthesizer"] == "done"
    assert len(body["manifest"]["docs"]) == 2
    assert (tmp_path / "runs" / run_id / "doc_0.json").exists()
    assert (tmp_path / "runs" / run_id / "doc_0.pdf").exists()
    assert (tmp_path / "runs" / run_id / "reports" / "synthesizer.json").exists()
    assert (tmp_path / "runs" / run_id / "reports" / "pdf.json").exists()
    synth_report = json.loads((tmp_path / "runs" / run_id / "reports" / "synthesizer.json").read_text())
    assert "privacy_safe" in synth_report
