import { useState } from "react";
import {
  ApiError,
  curate,
  hfPreview,
  runPipeline,
  samplePreview,
} from "../api/client";
import StageReport from "../components/StageReport";
import { useRun } from "../state/runStore";

type SourceType = "empty" | "sample" | "huggingface";

export default function CuratorPage() {
  const { runId, manifest, setManifest, setStep } = useRun();
  const req = manifest?.request as Record<string, unknown> | undefined;

  const [sourceType, setSourceType] = useState<SourceType>(
    (req?.source_type as SourceType) ?? "empty",
  );
  const [hfDataset, setHfDataset] = useState(String(req?.hf_dataset ?? ""));
  const [hfConfig, setHfConfig] = useState(String(req?.hf_config ?? ""));
  const [hfSplit, setHfSplit] = useState(String(req?.hf_split ?? "train"));
  const [prompt, setPrompt] = useState(String(req?.prompt ?? ""));
  const [numDocs, setNumDocs] = useState(Number(req?.num_docs ?? 5));
  const [docType, setDocType] = useState(String(req?.doc_type ?? ""));
  const [preview, setPreview] = useState("");
  const [running, setRunning] = useState<"curate" | "pipeline" | null>(null);
  const [error, setError] = useState<string | null>(null);

  function formatError(err: unknown): string {
    if (err instanceof ApiError) {
      const parts = [err.message];
      if (err.hint) parts.push(err.hint);
      return parts.join(" — ");
    }
    return err instanceof Error ? err.message : "Request failed";
  }

  async function handlePreviewHf() {
    if (!hfDataset.trim()) {
      setPreview("Enter a dataset name first.");
      return;
    }
    setPreview("Loading…");
    try {
      const data = await hfPreview(hfDataset.trim(), hfConfig || undefined, hfSplit, 3);
      setPreview(JSON.stringify(data.rows, null, 2));
    } catch (err) {
      setPreview(`Error: ${formatError(err)}`);
    }
  }

  async function handlePreviewSample() {
    setPreview("Loading…");
    try {
      const data = await samplePreview();
      setPreview(JSON.stringify(data.rows, null, 2));
    } catch (err) {
      setPreview(`Error: ${formatError(err)}`);
    }
  }

  function curateBody() {
    return {
      source_type: sourceType,
      hf_dataset: sourceType === "huggingface" ? hfDataset.trim() || null : null,
      hf_config: hfConfig.trim() || null,
      hf_split: hfSplit || "train",
    };
  }

  async function handleCurate(advance = true) {
    if (!runId) {
      setError("Create a run first.");
      return;
    }
    setRunning("curate");
    setError(null);
    try {
      const result = await curate(runId, curateBody());
      setManifest(result.manifest);
      if (advance) setStep(1);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setRunning(null);
    }
  }

  async function handleRunAll() {
    if (prompt.trim().length < 3) {
      setError("Enter a prompt (at least 3 characters) for Run all.");
      return;
    }
    setRunning("pipeline");
    setError(null);
    try {
      const body: Record<string, unknown> = {
        source_type: sourceType,
        prompt: prompt.trim(),
        num_docs: numDocs,
        hf_dataset: sourceType === "huggingface" ? hfDataset.trim() || null : null,
        hf_config: hfConfig.trim() || null,
        hf_split: hfSplit || "train",
      };
      if (docType) body.doc_type = docType;
      const m = await runPipeline(body);
      setManifest(m);
      setStep(2);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setRunning(null);
    }
  }

  return (
    <div className="page">
      <h1>NeMo Curator</h1>
      <p className="subtitle">
        Choose a seed source and curate training data for the synthetic OCR pipeline.
      </p>

      {!runId ? (
        <div className="error-box">Create a run using the header button to begin curating.</div>
      ) : null}

      {error ? <div className="error-box">{error}</div> : null}

      <div className="grid-2">
        <div className="card">
          <h2>Seed source</h2>
          <div className="radio-row">
            {(
              [
                ["empty", "Empty"],
                ["sample", "Sample data"],
                ["huggingface", "HuggingFace"],
              ] as const
            ).map(([value, label]) => (
              <label key={value}>
                <input
                  type="radio"
                  name="source"
                  value={value}
                  checked={sourceType === value}
                  onChange={() => setSourceType(value)}
                />
                {label}
              </label>
            ))}
          </div>

          {sourceType === "huggingface" ? (
            <div className="hf-fields">
              <label htmlFor="hf-dataset">HuggingFace dataset</label>
              <input
                id="hf-dataset"
                type="text"
                value={hfDataset}
                onChange={(e) => setHfDataset(e.target.value)}
                placeholder="e.g. gretelai/synthetic_text_to_sql"
              />
              <label htmlFor="hf-config">Config (optional)</label>
              <input
                id="hf-config"
                type="text"
                value={hfConfig}
                onChange={(e) => setHfConfig(e.target.value)}
              />
              <label htmlFor="hf-split">Split</label>
              <input
                id="hf-split"
                type="text"
                value={hfSplit}
                onChange={(e) => setHfSplit(e.target.value)}
              />
              <div className="hint">Rows are fetched via the datasets-server API.</div>
              <button type="button" className="secondary" onClick={handlePreviewHf}>
                Preview rows
              </button>
            </div>
          ) : null}

          {sourceType === "sample" ? (
            <button type="button" className="secondary" onClick={handlePreviewSample}>
              Preview sample rows
            </button>
          ) : null}

          {preview ? <pre className="preview-box">{preview}</pre> : null}

          <button
            type="button"
            className="block"
            disabled={!runId || running !== null}
            onClick={() => handleCurate(true)}
          >
            {running === "curate" ? "Running Curator…" : "Run Curator"}
          </button>
        </div>

        <div>
          <StageReport manifest={manifest} stage="curator" title="Curator report" />

          <div className="card">
            <h2>Run all stages</h2>
            <p className="hint">Shortcut: curate → design → synthesize in one call.</p>
            <label htmlFor="curator-prompt">Prompt</label>
            <textarea
              id="curator-prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. Pharmacy invoices from small Indian retailers with GST"
            />
            <label htmlFor="curator-doc-type">Document type</label>
            <select
              id="curator-doc-type"
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
            >
              <option value="">Auto (Data Designer decides)</option>
              <option value="invoice">Invoice</option>
              <option value="receipt">Receipt</option>
              <option value="letter">Letter</option>
              <option value="form">Form</option>
            </select>
            <label htmlFor="curator-num-docs">Number of documents</label>
            <input
              id="curator-num-docs"
              type="number"
              min={1}
              max={50}
              value={numDocs}
              onChange={(e) => setNumDocs(Number(e.target.value))}
            />
            <button
              type="button"
              className="block"
              disabled={running !== null}
              onClick={handleRunAll}
            >
              {running === "pipeline" ? "Running pipeline…" : "Run all"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
