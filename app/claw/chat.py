"""Chat loop: load history, invoke provider, persist messages."""
from __future__ import annotations

from .. import storage
from ..pipeline.llm import LLMClient
from .provider import InAppClawProvider


def handle_claw_chat(run_id: str, message: str, provider: InAppClawProvider | None = None) -> dict:
    try:
        storage.load_manifest(run_id)
    except (FileNotFoundError, ValueError):
        return {
            "reply": "Run not found.",
            "tool_calls": [],
            "messages": [{"role": "assistant", "content": "Run not found."}],
        }

    history = storage.load_claw_messages(run_id)
    claw = provider or InAppClawProvider(LLMClient())
    result = claw.chat(run_id, message, history)
    storage.save_claw_messages(run_id, result["messages"])
    return result
