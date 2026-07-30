import { useEffect, useState } from "react";
import {
  ApiError,
  health,
  listRuns,
  runEval,
} from "../api/client";
import MetricTiles, { fmtPct } from "../components/MetricTiles";
import { useRun } from "../state/runStore";

type RunOption = {
  run_id: string;
  doc_type?: string;
  num_docs?: number;
  prompt?: string;
};

type DocEval = {
  index: number;
  field_accuracy?: number;
  fuzzy_field_accuracy?: number;
  cer?: number;
  wer?: number;
  structure_f1?: number;
  matched_fields?: number;
  total_fields?: number;
  error?: string;
  fields?: Array<{
    field: string;
    expected?: unknown;
    predicted?: unknown;
    match: string;
  }>;
};

type EvalResult = {
  eval_id: string;
  run_id: string;
  mode: string;
  model_name?: string;
  aggregate?: Record<string, number>;
  docs?: DocEval[];
};

type ProviderId =
  | "nvidia"
  | "openai"
  | "openrouter"
  | "gemini"
  | "anthropic"
  | "azure"
  | "github"
  | "custom";

const PROVIDER_PRESETS: Record<
  ProviderId,
  { baseUrl: string; modelPlaceholder: string; keyPlaceholder: string; hint: string }
> = {
  nvidia: {
    baseUrl: "https://integrate.api.nvidia.com/v1",
    modelPlaceholder: "meta/llama-3.2-90b-vision-instruct",
    keyPlaceholder: "nvapi-…",
    hint: "NVIDIA NIM — get a free API key at build.nvidia.com.",
  },
  openai: {
    baseUrl: "https://api.openai.com/v1",
    modelPlaceholder: "gpt-4o-mini",
    keyPlaceholder: "sk-…",
    hint: "OpenAI — keys at platform.openai.com/api-keys.",
  },
  openrouter: {
    baseUrl: "https://openrouter.ai/api/v1",
    modelPlaceholder: "openai/gpt-4o-mini",
    keyPlaceholder: "sk-or-…",
    hint: "OpenRouter — one key for many models.",
  },
  gemini: {
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    modelPlaceholder: "gemini-2.0-flash",
    keyPlaceholder: "AIza…",
    hint: "Google Gemini via OpenAI-compatible endpoint.",
  },
  anthropic: {
    baseUrl: "https://api.anthropic.com/v1",
    modelPlaceholder: "claude-3-5-sonnet-20241022",
    keyPlaceholder: "sk-ant-…",
    hint: "Anthropic Claude via OpenAI-compatible endpoint.",
  },
  azure: {
    baseUrl: "",
    modelPlaceholder: "your deployment name",
    keyPlaceholder: "Azure API key",
    hint: "Paste full Azure OpenAI deployment URL as Base URL.",
  },
  github: {
    baseUrl: "https://models.github.ai/inference",
    modelPlaceholder: "openai/gpt-4o-mini",
    keyPlaceholder: "ghp_…",
    hint: "GitHub Models — PAT with models:read.",
  },
  custom: {
    baseUrl: "",
    modelPlaceholder: "e.g. my-model",
    keyPlaceholder: "API key (optional)",
    hint: "Any OpenAI-compatible /chat/completions vision endpoint.",
  },
};

export default function EvaluatorPage() {
  const { runId } = useRun();

  const [runs, setRuns] = useState<RunOption[]>([]);
  const [selectedRun, setSelectedRun] = useState(runId ?? "");
  const [mode, setMode] = useState<"model" | "upload">("upload");
  const [provider, setProvider] = useState<ProviderId>("nvidia");
  const [baseUrl, setBaseUrl] = useState(PROVIDER_PRESETS.nvidia.baseUrl);
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [nvidiaOverride, setNvidiaOverride] = useState(false);
  const [serverHasNvidiaKey, setServerHasNvidiaKey] = useState(false);
  const [predictions, setPredictions] = useState('{"0": {}}');
  const [result, setResult] = useState<EvalResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRuns()
      .then((data) => setRuns(data as RunOption[]))
      .catch(() => setRuns([]));
  }, []);

  useEffect(() => {
    if (runId) setSelectedRun(runId);
  }, [runId]);

  useEffect(() => {
    health()
      .then((h) => {
        const data = h as { llm_available?: boolean };
        setServerHasNvidiaKey(!!data.llm_available);
      })
      .catch(() => setServerHasNvidiaKey(false));
  }, []);

  useEffect(() => {
    const preset = PROVIDER_PRESETS[provider];
    setBaseUrl(preset.baseUrl);
  }, [provider]);

  const usingNvidiaDefaults =
    provider === "nvidia" && serverHasNvidiaKey && !nvidiaOverride;

  function formatError(err: unknown): string {
    if (err instanceof ApiError) return err.message;
    return err instanceof Error ? err.message : "Evaluation failed";
  }

  async function handleEval() {
    if (!selectedRun) {
      setError("Select a dataset run.");
      return;
    }
    setRunning(true);
    setError(null);

    const body: Record<string, unknown> = { run_id: selectedRun, mode };
    if (mode === "model") {
      if (!usingNvidiaDefaults && (!baseUrl.trim() || !modelName.trim())) {
        setError("Base URL and model name are required.");
        setRunning(false);
        return;
      }
      body.model_config = {
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        model: modelName.trim(),
        provider,
      };
    } else {
      try {
        body.predictions = JSON.parse(predictions);
      } catch (err) {
        setError(`Predictions must be valid JSON: ${formatError(err)}`);
        setRunning(false);
        return;
      }
    }

    try {
      const data = (await runEval(body)) as EvalResult;
      setResult(data);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="page">
      <h1>NeMo Evaluator</h1>
      <p className="subtitle">
        Score your OCR model against generated JSON ground truth and PDF structure.
      </p>

      <div className="grid-2">
        <div className="card">
          <h2>Evaluation setup</h2>

          <label htmlFor="eval-run">Dataset run</label>
          <select
            id="eval-run"
            value={selectedRun}
            onChange={(e) => setSelectedRun(e.target.value)}
          >
            <option value="">Select a run…</option>
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {run.run_id.slice(0, 14)} · {run.doc_type ?? "?"} · {run.num_docs ?? 0} docs
              </option>
            ))}
          </select>

          <label>Prediction source</label>
          <div className="radio-row">
            <label>
              <input
                type="radio"
                name="eval-mode"
                value="model"
                checked={mode === "model"}
                onChange={() => setMode("model")}
              />
              Call my model
            </label>
            <label>
              <input
                type="radio"
                name="eval-mode"
                value="upload"
                checked={mode === "upload"}
                onChange={() => setMode("upload")}
              />
              Upload predictions
            </label>
          </div>

          {mode === "model" ? (
            <div>
              <label htmlFor="provider">Provider</label>
              <select
                id="provider"
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value as ProviderId);
                  setNvidiaOverride(false);
                }}
              >
                {Object.keys(PROVIDER_PRESETS).map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
              <p className="hint">{PROVIDER_PRESETS[provider].hint}</p>

              {usingNvidiaDefaults ? (
                <div className="hint">
                  Using server NVIDIA_API_KEY — no setup needed.
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={nvidiaOverride}
                      onChange={(e) => setNvidiaOverride(e.target.checked)}
                    />
                    Use a different NVIDIA key, endpoint or model
                  </label>
                </div>
              ) : null}

              {!usingNvidiaDefaults ? (
                <div>
                  <label htmlFor="base-url">Base URL</label>
                  <input
                    id="base-url"
                    type="text"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder={PROVIDER_PRESETS[provider].baseUrl || "https://…/v1"}
                  />
                  <label htmlFor="api-key">API key</label>
                  <input
                    id="api-key"
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={PROVIDER_PRESETS[provider].keyPlaceholder}
                  />
                  <label htmlFor="model-name">Model</label>
                  <input
                    id="model-name"
                    type="text"
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                    placeholder={PROVIDER_PRESETS[provider].modelPlaceholder}
                  />
                </div>
              ) : null}
            </div>
          ) : (
            <div>
              <label htmlFor="predictions">Predictions JSON</label>
              <textarea
                id="predictions"
                className="schema-view"
                value={predictions}
                onChange={(e) => setPredictions(e.target.value)}
                placeholder='{"0": {"vendor_name": "…"}, "1": {…}}'
              />
              <p className="hint">Object keyed by document index with extracted JSON.</p>
            </div>
          )}

          {error ? <div className="error-box">{error}</div> : null}

          <button type="button" className="block" disabled={running} onClick={handleEval}>
            {running ? "Evaluating…" : "Run evaluation"}
          </button>
        </div>

        <div>
          {result ? (
            <div className="card">
              <h2>
                Results <span className="badge">{result.eval_id?.slice(0, 12)}</span>
              </h2>
              <MetricTiles aggregate={result.aggregate ?? {}} />

              <h2 style={{ marginTop: 22 }}>Per-document detail</h2>
              <DocEvalTable docs={result.docs ?? []} />
            </div>
          ) : (
            <div className="card">
              <div className="empty">Run an evaluation to see the accuracy dashboard.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DocEvalTable({ docs }: { docs: DocEval[] }) {
  if (!docs.length) return <div className="empty">No documents scored.</div>;

  return (
    <table>
      <thead>
        <tr>
          <th>Doc</th>
          <th className="num">Fields</th>
          <th className="num">Exact</th>
          <th className="num">Fuzzy</th>
          <th className="num">CER</th>
          <th className="num">WER</th>
          <th className="num">Struct F1</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {docs.map((doc) => (
          <tr key={doc.index}>
            <td>doc_{doc.index}</td>
            {doc.error ? (
              <td colSpan={7} className="match-miss">
                error: {doc.error}
              </td>
            ) : (
              <>
                <td className="num">
                  {doc.matched_fields}/{doc.total_fields}
                </td>
                <td className="num">{fmtPct(doc.field_accuracy)}</td>
                <td className="num">{fmtPct(doc.fuzzy_field_accuracy)}</td>
                <td className="num">{fmtPct(doc.cer)}</td>
                <td className="num">{fmtPct(doc.wer)}</td>
                <td className="num">{fmtPct(doc.structure_f1)}</td>
              </>
            )}
            <td>
              {doc.fields && doc.fields.length > 0 ? (
                <details className="fields">
                  <summary>fields</summary>
                  <table>
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Expected</th>
                        <th>Predicted</th>
                        <th>Match</th>
                      </tr>
                    </thead>
                    <tbody>
                      {doc.fields.map((f) => (
                        <tr key={f.field}>
                          <td>{f.field}</td>
                          <td>{String(f.expected ?? "")}</td>
                          <td>{String(f.predicted ?? "∅")}</td>
                          <td className={`match-${f.match}`}>{f.match}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
