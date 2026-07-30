type Aggregate = Record<string, number | null | undefined>;

const TILE_DEFS = [
  ["field_accuracy", "Field accuracy", "exact matches / fields"],
  ["fuzzy_field_accuracy", "Fuzzy accuracy", "mean per-field similarity"],
  ["cer", "CER", "character error rate (lower is better)"],
  ["wer", "WER", "word error rate (lower is better)"],
  ["structure_f1", "Structure F1", "JSON key-tree overlap"],
] as const;

function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "–";
  return `${(value * 100).toFixed(1)}%`;
}

type MetricTilesProps = {
  aggregate: Aggregate;
};

export default function MetricTiles({ aggregate }: MetricTilesProps) {
  return (
    <div className="tiles">
      {TILE_DEFS.map(([key, label, sub]) => (
        <div key={key} className="tile">
          <div className="label">{label}</div>
          <div className="value">{fmtPct(aggregate[key] as number | undefined)}</div>
          <div className="sub">{sub}</div>
        </div>
      ))}
    </div>
  );
}

export { fmtPct };
