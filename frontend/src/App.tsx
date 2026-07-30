import { useState } from "react";
import { ApiError, createRun } from "./api/client";
import Stepper from "./components/Stepper";
import CuratorPage from "./pages/CuratorPage";
import DesignerPage from "./pages/DesignerPage";
import SynthesizerPage from "./pages/SynthesizerPage";
import ClawPage from "./pages/ClawPage";
import ClawRail from "./components/ClawRail";
import { useRun } from "./state/runStore";

function StageContent({ step }: { step: number }) {
  switch (step) {
    case 0:
      return <CuratorPage />;
    case 1:
      return <DesignerPage />;
    case 2:
      return <SynthesizerPage />;
    case 3:
      return <ClawPage />;
    default:
      return (
        <p className="subtitle">Stage {step + 1} — coming soon.</p>
      );
  }
}

export default function App() {
  const { runId, manifest, setManifest, setStep, step } = useRun();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreateRun() {
    setCreating(true);
    setError(null);
    try {
      const manifest = await createRun({ prompt: "", source_type: "empty" });
      if (!manifest.run_id) {
        throw new Error("Create run returned no run_id");
      }
      setManifest(manifest);
      setStep(0);
    } catch (err) {
      if (err instanceof ApiError) {
        const parts = [err.message];
        if (err.hint) parts.push(err.hint);
        setError(parts.join(" — "));
      } else {
        setError(err instanceof Error ? err.message : "Create run failed");
      }
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

      <Stepper />

      <div className="app-body">
        <main>
          {error ? <div className="error-box">{error}</div> : null}
          {manifest?.stage_error ? (
            <div className="error-box" role="alert">
              {manifest.stage_error.stage}: {manifest.stage_error.error}
              {manifest.stage_error.hint ? ` — ${manifest.stage_error.hint}` : ""}
            </div>
          ) : null}
          <StageContent step={step} />
        </main>
        {runId && step !== 3 ? <ClawRail runId={runId} /> : null}
      </div>
    </>
  );
}
