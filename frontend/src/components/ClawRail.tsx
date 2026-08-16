import { useEffect, useRef, useState } from "react";
import { ApiError, clawChat } from "../api/client";
import { useRun } from "../state/runStore";

type ToolCall = {
  tool?: string;
  args?: unknown;
  result?: unknown;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCall[];
};

const SUGGESTIONS = [
  "What failed?",
  "Re-run synthesizer",
  "Show curator report",
] as const;

type ClawRailProps = {
  runId: string;
  compact?: boolean;
  onActivity?: (entry: { type: string; detail: string }) => void;
};

const MUTATING_TOOLS = new Set(["run_stage", "run_pipeline"]);

export default function ClawRail({ runId, compact = true, onActivity }: ClawRailProps) {
  const { refresh } = useRun();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  async function sendMessage(text: string) {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    setSending(true);
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setInput("");

    try {
      const result = await clawChat(runId, trimmed);
      const toolCalls = (result.tool_calls ?? []) as ToolCall[];
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: result.reply, toolCalls },
      ]);
      for (const tc of toolCalls) {
        onActivity?.({
          type: "tool",
          detail: `${tc.tool ?? "tool"}: ${JSON.stringify(tc.result ?? {}).slice(0, 120)}`,
        });
      }
      onActivity?.({ type: "reply", detail: result.reply });

      if (toolCalls.some((tc) => MUTATING_TOOLS.has(tc.tool ?? ""))) {
        try {
          await refresh();
        } catch (refreshErr) {
          const refreshMsg =
            refreshErr instanceof ApiError
              ? refreshErr.message
              : refreshErr instanceof Error
                ? refreshErr.message
                : "Failed to refresh run";
          setError(`Chat ok, but refresh failed: ${refreshMsg}`);
        }
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Chat failed";
      setError(msg);
      setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${msg}` }]);
    } finally {
      setSending(false);
    }
  }

  return (
    <aside className={`claw-rail${compact ? " compact" : ""}`}>
      <div className="claw-rail-head">
        <strong>NeMo Claw</strong>
      </div>

      <div className="suggestion-chips">
        {SUGGESTIONS.map((chip) => (
          <button
            key={chip}
            type="button"
            className="chip"
            disabled={sending}
            onClick={() => sendMessage(chip)}
          >
            {chip}
          </button>
        ))}
      </div>

      <div className="claw-messages" ref={listRef}>
        {messages.length === 0 ? (
          <p className="hint">Ask about stage status, reports, or re-run steps.</p>
        ) : null}
        {messages.map((msg, i) => (
          <div key={i} className={`claw-msg ${msg.role}`}>
            <div className="claw-msg-body">{msg.content}</div>
            {msg.toolCalls && msg.toolCalls.length > 0 ? (
              <div className="tool-chips">
                {msg.toolCalls.map((tc, j) => (
                  <span key={j} className="tool-chip" title={JSON.stringify(tc.result)}>
                    {tc.tool ?? "tool"}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {sending ? <div className="claw-msg assistant">Thinking…</div> : null}
      </div>

      {error ? <div className="error-box claw-error">{error}</div> : null}

      <form
        className="claw-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          sendMessage(input);
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message NeMo Claw…"
          disabled={sending}
        />
        <button type="submit" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}
