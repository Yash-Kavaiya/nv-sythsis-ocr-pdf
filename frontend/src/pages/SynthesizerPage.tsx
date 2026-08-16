import { useState } from "react";
import { ApiError, synthesize } from "../api/client";
import DocGrid from "../components/DocGrid";
import StageReport from "../components/StageReport";
import { useRun } from "../state/runStore";

export default function SynthesizerPage() {
  const { runId, manifest, setManifest, setStep } = useRun();
  const req = manifest?.request as Record<string, unknown> | undefined;
  const schema = manifest?.schema as Record<string, unknown> | undefined;

  const [numDocs, setNumDocs] = useState(Number(req?.num_docs ?? 5));
  const [seed, setSeed] = useState<string>(req?.seed != null ? String(req.seed) : "");
  const [privacySafe, setPrivacySafe] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isStale = manifest?.stage_status?.synthesizer === "stale";
  const docs = (manifest?.docs ?? []) as Array<{
    index: number;
    json_path?: string;
    pdf_path?: string;
    png_path?: string | null;
  }>;

  function formatError(err: unknown): string {
    if (err instanceof ApiError) {
      const parts = [err.message];
      if (err.hint) parts.push(err.hint);
      return parts.join(" — ");
    }
    return err instanceof Error ? err.message : "Request failed";
  }

  async function handleSynthesize(advance = true) {
    if (!runId) {
      setError("Create a run first.");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        num_docs: numDocs,
        privacy_safe: privacySafe,
      };
      if (seed.trim()) body.seed = Number(seed);
      const result = await synthesize(runId, body);
      setManifest(result.manifest);
      if (advance) setStep(3);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <h1>NeMo Safe Synthesizer</h1>
      <p className="subtitle">
        Generate synthetic documents with JSON ground truth, LaTeX harness, and PDF output.
      </p>

      {isStale ? (
        <div className="stale-banner" role="status">
          Upstream stages changed — re-run synthesize to refresh documents.
        </div>
      ) : null}

      {!runId ? (
        <div className="error-box">Create a run and complete Data Designer first.</div>
      ) : null}

      {error ? <div className="error-box">{error}</div> : null}

      <div className="grid-2">
        <div className="card">
          <h2>Synthesis settings</h2>
          <label htmlFor="synth-num-docs">Number of documents</label>
          <input
            id="synth-num-docs"
            type="number"
            min={1}
            max={50}
            value={numDocs}
            onChange={(e) => setNumDocs(Number(e.target.value))}
          />
          <label htmlFor="synth-seed">Seed (optional)</label>
          <input
            id="synth-seed"
            type="number"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            placeholder="Random if empty"
          />
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={privacySafe}
              onChange={(e) => setPrivacySafe(e.target.checked)}
            />
            Privacy-safe synthesis
          </label>
          <button
            type="button"
            className="block"
            disabled={!runId || running}
            onClick={() => handleSynthesize(true)}
          >
            {running ? "Running Synthesize…" : "Run Synthesize"}
          </button>
        </div>

        <div>
          {runId && docs.length > 0 ? (
            <div className="card">
              <h2>
                Generated documents
                <a className="badge download-link" href={`/api/runs/${runId}/dataset`}>
                  Download dataset ↓
                </a>
              </h2>
              <DocGrid
                runId={runId}
                docs={docs}
                docType={schema?.doc_type as string | undefined}
              />
            </div>
          ) : null}
          <StageReport manifest={manifest} stage="synthesizer" title="Synthesizer report" />
        </div>
      </div>
    </div>
  );
}
