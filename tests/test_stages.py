# tests/test_stages.py
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
