import { isStepEnabled, STAGE_KEYS, useRun } from "../state/runStore";

const STEP_LABELS = [
  "Curator",
  "Data Designer",
  "Safe Synthesizer",
  "Claw",
  "Evaluator",
] as const;

function formatStatus(status: string | undefined): string {
  if (!status) return "Pending";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export default function Stepper() {
  const { runId, manifest, step, setStep } = useRun();
  const stageStatus = manifest?.stage_status;

  return (
    <nav className="stepper" aria-label="Pipeline stages">
      {STEP_LABELS.map((label, index) => {
        const enabled = isStepEnabled(index, runId, stageStatus);
        const stageKey = STAGE_KEYS[index];
        const status = stageStatus?.[stageKey];
        return (
          <button
            key={label}
            type="button"
            className={`stage${index === step ? " active" : ""}${!enabled ? " locked" : ""}`}
            onClick={() => setStep(index)}
            disabled={!enabled}
            aria-current={index === step ? "step" : undefined}
          >
            <span className="name">{label}</span>
            <span className="status">{formatStatus(status)}</span>
          </button>
        );
      })}
    </nav>
  );
}
