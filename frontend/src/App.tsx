import { useState } from "react";

const STEPS = [
  "Curator",
  "Data Designer",
  "Safe Synthesizer",
  "Claw",
  "Evaluator",
] as const;

type CreateRunResponse = {
  run_id: string;
};

export default function App() {
  const [activeStep, setActiveStep] = useState(0);
  const [runId, setRunId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreateRun() {
    setCreating(true);
    setError(null);
    try {
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: "", source_type: "empty" }),
      });
      if (!res.ok) {
        throw new Error(`Create run failed (${res.status})`);
      }
      const data = (await res.json()) as CreateRunResponse;
      setRunId(data.run_id);
      setActiveStep(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create run failed");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <header>
        <div className="logo">
          <span className="nv">▮</span>
          NeMo Synthetic OCR Studio
        </div>
        <button type="button" onClick={handleCreateRun} disabled={creating}>
          {creating ? "Creating…" : "Create run"}
        </button>
        {runId ? <span className="run-id">Run: {runId}</span> : null}
      </header>

      <nav className="stepper" aria-label="Pipeline stages">
        {STEPS.map((label, index) => (
          <button
            key={label}
            type="button"
            className={`stage${index === activeStep ? " active" : ""}`}
            onClick={() => setActiveStep(index)}
          >
            <span className="name">{label}</span>
            <span className="status">Pending</span>
          </button>
        ))}
      </nav>

      <main>
        {error ? <div className="error-box">{error}</div> : null}
        <p className="subtitle">
          {runId
            ? `Run ${runId} — select a stage above to begin.`
            : "Create a run to start the wizard."}
        </p>
      </main>
    </>
  );
}
