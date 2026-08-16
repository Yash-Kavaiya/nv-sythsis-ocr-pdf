import type { Manifest } from "../api/client";

type StageReportProps = {
  manifest: Manifest | null;
  stage: string;
  title?: string;
};

const SKIP_KEYS = new Set(["example", "seed_stats"]);

function formatDetail(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .filter(([k]) => !SKIP_KEYS.has(k))
    .map(([k, v]) => {
      const val =
        typeof v === "object" && v !== null ? JSON.stringify(v).slice(0, 120) : String(v);
      return `${k}: ${val}`;
    })
    .join("\n");
}

export default function StageReport({ manifest, stage, title }: StageReportProps) {
  const entry = manifest?.stages?.find((s) => s.stage === stage);
  if (!entry?.detail || Object.keys(entry.detail).length === 0) {
    return null;
  }

  const detail = entry.detail as Record<string, unknown>;
  const status = manifest?.stage_status?.[stage];

  return (
    <div className="card stage-report">
      <h2>{title ?? `${stage} report`}</h2>
      {status ? (
        <p className="hint">
          Status: <strong>{status}</strong>
        </p>
      ) : null}
      <pre className="report-body">{formatDetail(detail)}</pre>
    </div>
  );
}
