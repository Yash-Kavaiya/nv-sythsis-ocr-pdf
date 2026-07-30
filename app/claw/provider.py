"""Claw provider implementations: in-app LLM/heuristic and future NemoClaw stub."""
from __future__ import annotations

import json
from typing import Any, Protocol

from ..pipeline.llm import LLMClient, ensure_json_object
from .tools import TOOL_NAMES, execute_tool

MAX_TOOL_ROUNDS = 2

SYSTEM_PROMPT = """You are NeMo Claw, an orchestrator for the synthetic OCR document pipeline.
You can call tools by responding with JSON: {"tool": "<name>", "args": {...}}.
Available tools: """ + ", ".join(TOOL_NAMES) + """.
If no tool is needed, reply with plain text.
After a tool runs you will receive the observation; then give a concise final answer."""

OFFLINE_HELP = (
    "NeMo Claw (offline). I can help with: get_manifest (stage status), "
    "get_report (curator/designer/synthesizer), list_docs, run_pipeline, "
    "run_stage (curate/design/synthesize), suggest_fix, start_eval. "
    "Try asking about stage status, reports, or errors."
)


class ClawProvider(Protocol):
    def chat(self, run_id: str, message: str, history: list[dict]) -> dict: ...


class InAppClawProvider:
    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()

    def chat(self, run_id: str, message: str, history: list[dict]) -> dict:
        tool_calls: list[dict[str, Any]] = []
        working_history = list(history)

        user_entry = {"role": "user", "content": message}
        working_history.append(user_entry)

        if not self.llm.available:
            return self._offline_chat(run_id, message, working_history, tool_calls)

        return self._llm_chat(run_id, message, working_history, tool_calls)

    def _offline_chat(
        self,
        run_id: str,
        message: str,
        working_history: list[dict],
        tool_calls: list[dict[str, Any]],
    ) -> dict:
        picked = _heuristic_tool(message)
        if picked:
            tool_name, args = picked
            result = execute_tool(tool_name, args, run_id)
            tool_calls.append({"tool": tool_name, "args": args, "result": result})
            working_history.append({"role": "tool", "tool": tool_name, "content": result})
            reply = _format_tool_reply(tool_name, result)
        else:
            reply = OFFLINE_HELP

        working_history.append({"role": "assistant", "content": reply})
        return {"reply": reply, "tool_calls": tool_calls, "messages": working_history}

    def _llm_chat(
        self,
        run_id: str,
        message: str,
        working_history: list[dict],
        tool_calls: list[dict[str, Any]],
    ) -> dict:
        llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for entry in working_history:
            role = entry.get("role", "user")
            if role == "tool":
                llm_messages.append({
                    "role": "user",
                    "content": f"Tool {entry.get('tool')} result: {json.dumps(entry.get('content', {}), default=str)}",
                })
            else:
                llm_messages.append({"role": role, "content": entry.get("content", "")})

        reply = ""
        for _ in range(MAX_TOOL_ROUNDS + 1):
            try:
                raw = self.llm.chat(llm_messages, temperature=0.3)
            except Exception:
                return self._offline_chat(run_id, message, working_history, tool_calls)

            tool_call = _parse_tool_call(raw)
            if tool_call is None:
                reply = raw.strip() or OFFLINE_HELP
                break

            tool_name, args = tool_call
            result = execute_tool(tool_name, args, run_id)
            tool_calls.append({"tool": tool_name, "args": args, "result": result})
            working_history.append({"role": "tool", "tool": tool_name, "content": result})
            llm_messages.append({"role": "assistant", "content": raw})
            llm_messages.append({
                "role": "user",
                "content": f"Tool {tool_name} result: {json.dumps(result, default=str)}. Give final answer.",
            })

        if not reply and tool_calls:
            reply = _format_tool_reply(tool_calls[-1]["tool"], tool_calls[-1]["result"])
        if not reply:
            reply = OFFLINE_HELP

        working_history.append({"role": "assistant", "content": reply})
        return {"reply": reply, "tool_calls": tool_calls, "messages": working_history}


class NemoClawProvider:
    def chat(self, run_id: str, message: str, history: list[dict]) -> dict:
        raise NotImplementedError(
            "Real NemoClaw/OpenShell is not wired in v1. Use InAppClawProvider."
        )


def _heuristic_tool(message: str) -> tuple[str, dict[str, Any]] | None:
    lower = message.lower()
    if any(k in lower for k in ("manifest", "status", "stage", "done", "progress")):
        return "get_manifest", {}
    if "report" in lower:
        stage = "curator"
        for s in ("curator", "designer", "synthesizer", "pdf"):
            if s in lower:
                stage = s
                break
        return "get_report", {"stage": stage}
    if any(k in lower for k in ("doc", "document", "pdf", "artifact")):
        return "list_docs", {}
    if any(k in lower for k in ("fix", "error", "fail", "recover", "suggest")):
        return "suggest_fix", {}
    if "eval" in lower:
        return "start_eval", {}
    if "pipeline" in lower or "run all" in lower:
        return "run_pipeline", {}
    for stage in ("curate", "design", "synthesize"):
        if stage in lower and any(k in lower for k in ("run", "start", "retry", "re-run")):
            return "run_stage", {"stage": stage}
    return None


def _parse_tool_call(raw: str) -> tuple[str, dict[str, Any]] | None:
    try:
        obj = ensure_json_object(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    tool = obj.get("tool")
    if not tool or tool not in TOOL_NAMES:
        return None
    args = obj.get("args", {})
    if not isinstance(args, dict):
        args = {}
    return tool, args


def _format_tool_reply(tool_name: str, result: dict[str, Any]) -> str:
    if not result.get("ok", True) and "error" in result:
        hint = result.get("hint", "")
        suffix = f" Hint: {hint}" if hint else ""
        return f"{tool_name} failed: {result['error']}.{suffix}"

    if tool_name == "get_manifest":
        status = result.get("stage_status", {})
        parts = [f"{stage}: {state}" for stage, state in status.items()]
        return "Stage status — " + ", ".join(parts) if parts else "Manifest loaded."

    if tool_name == "get_report":
        return f"Report for {result.get('stage', 'stage')} retrieved."

    if tool_name == "list_docs":
        return f"Found {result.get('count', 0)} document(s)."

    if tool_name == "suggest_fix":
        suggestions = result.get("suggestions", [])
        if suggestions:
            return "Suggestions: " + " ".join(suggestions)
        return "No fix suggestions available."

    if tool_name == "start_eval":
        return result.get("message", "Evaluator ready.")

    if tool_name in ("run_pipeline", "run_stage"):
        manifest = result.get("manifest", {})
        status = manifest.get("stage_status", {})
        return "Pipeline updated. " + ", ".join(f"{k}={v}" for k, v in status.items())

    return json.dumps(result, default=str)[:500]
