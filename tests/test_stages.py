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
    from app.main import app
    return TestClient(app)


def test_create_run_writes_manifest(client, tmp_path):
    r = client.post("/api/runs", json={"prompt": "pharmacy invoices", "source_type": "empty"})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"].startswith("run_")
    assert (tmp_path / "runs" / body["run_id"] / "manifest.json").exists()
    assert body["stage_status"]["curator"] == "idle"
