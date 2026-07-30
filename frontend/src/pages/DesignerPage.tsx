import { useState } from "react";
import { ApiError, design } from "../api/client";
import StageReport from "../components/StageReport";
import { useRun } from "../state/runStore";

export default function DesignerPage() {
  const { runId, manifest, setManifest, setStep } = useRun();
  const req = manifest?.request as Record<string, unknown> | undefined;

  const [prompt, setPrompt] = useState(String(req?.prompt ?? ""));
  const [docType, setDocType] = useState(String(req?.doc_type ?? ""));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const schemaJson = manifest?.schema
    ? JSON.stringify(manifest.schema, null, 2)
    : "";

  function formatError(err: unknown): string {
    if (err instanceof ApiError) {
      const parts = [err.message];
      if (err.hint) parts.push(err.hint);
      return parts.join(" — ");
    }
    return err instanceof Error ? err.message : "Request failed";
  }

  async function handleDesign(advance = true) {
    if (!runId) {
      setError("Create a run first.");
      return;
    }
    if (prompt.trim().length < 3) {
      setError("Enter a prompt (at least 3 characters).");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { prompt: prompt.trim() };
      if (docType) body.doc_type = docType;
      const result = await design(runId, body);
      setManifest(result.manifest);
      if (advance) setStep(2);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <h1>NeMo Data Designer</h1>
      <p className="subtitle">
        Define the document schema from your prompt. Re-run design to refresh the schema.
      </p>

      {!runId ? (
        <div className="error-box">Create a run and complete Curator to use the Data Designer.</div>
      ) : null}

      {error ? <div className="error-box">{error}</div> : null}

      <div className="grid-2">
        <div className="card">
          <h2>Design input</h2>
          <label htmlFor="design-prompt">Prompt</label>
          <textarea
            id="design-prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. Pharmacy invoices from small Indian retailers with GST, in rupees"
          />
          <label htmlFor="design-doc-type">Document type</label>
          <select
            id="design-doc-type"
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
          >
            <option value="">Auto (infer from prompt)</option>
            <option value="invoice">Invoice</option>
            <option value="receipt">Receipt</option>
            <option value="letter">Letter</option>
            <option value="form">Form</option>
          </select>
          <button
            type="button"
            className="block"
            disabled={!runId || running}
            onClick={() => handleDesign(true)}
          >
            {running ? "Running Designer…" : "Run Designer"}
          </button>
        </div>

        <div>
          <div className="card">
            <h2>Schema JSON</h2>
            <p className="hint">Display only — edit the prompt and re-run design to change.</p>
            <textarea
              className="schema-view"
              readOnly
              value={schemaJson}
              placeholder="Run Designer to generate a schema."
            />
          </div>
          <StageReport manifest={manifest} stage="designer" title="Designer report" />
        </div>
      </div>
    </div>
  );
}
