# tests/test_claw.py
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
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


def test_get_manifest_tool(client):
    run_id = client.post("/api/runs", json={"prompt": "x"}).json()["run_id"]
    from app.claw.tools import execute_tool
    out = execute_tool("get_manifest", {}, run_id)
    assert out["run_id"] == run_id


def test_claw_chat_offline_no_crash(client, monkeypatch):
    import app.pipeline.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMClient, "available", property(lambda self: False))
    run_id = client.post("/api/runs", json={"prompt": "x"}).json()["run_id"]
    r = client.post("/api/claw/chat", json={"run_id": run_id, "message": "What stages are done?"})
    assert r.status_code == 200
    body = r.json()
    assert "reply" in body
    assert "tool_calls" in body
    assert "messages" in body


def test_claw_chat_persists_messages(client, monkeypatch, tmp_path):
    import app.pipeline.llm as llm_mod
    monkeypatch.setattr(llm_mod.LLMClient, "available", property(lambda self: False))
    run_id = client.post("/api/runs", json={"prompt": "x"}).json()["run_id"]
    client.post("/api/claw/chat", json={"run_id": run_id, "message": "hello"})
    path = tmp_path / "runs" / run_id / "claw" / "messages.json"
    assert path.exists()
    messages = json.loads(path.read_text())
    assert len(messages) >= 2


def test_nemo_claw_provider_stub():
    from app.claw.provider import NemoClawProvider
    provider = NemoClawProvider()
    with pytest.raises(NotImplementedError, match="OpenShell"):
        provider.chat("run_x", "hi", [])


def test_run_stage_tool_updates_manifest_request(client):
    run_id = client.post("/api/runs", json={"prompt": "invoices", "source_type": "empty"}).json()["run_id"]
    from app.claw.tools import execute_tool

    client.post(f"/api/runs/{run_id}/curate", json={"source_type": "empty"})
    client.post(f"/api/runs/{run_id}/design", json={"prompt": "retail invoices USD"})
    out = execute_tool("run_stage", {"stage": "synthesize", "num_docs": 2, "seed": 7}, run_id)
    assert out["ok"] is True
    m = client.get(f"/api/runs/{run_id}").json()
    assert m["request"]["num_docs"] == 2
    assert m["request"]["seed"] == 7
