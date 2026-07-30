import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { getRun, type Manifest } from "../api/client";

export const STAGE_KEYS = [
  "curator",
  "designer",
  "synthesizer",
  "claw",
  "evaluator",
] as const;

export type RunState = {
  runId: string | null;
  manifest: Manifest | null;
  step: number;
  setStep: (n: number) => void;
  refresh: () => Promise<void>;
  setManifest: (m: Manifest) => void;
};

const RunContext = createContext<RunState | null>(null);

export function isStepEnabled(
  stepIndex: number,
  runId: string | null,
  stageStatus: Record<string, string> | undefined,
): boolean {
  if (stepIndex === 0) return true;
  if (!runId) return false;
  const status = stageStatus ?? {};
  for (let i = 0; i < stepIndex; i++) {
    const key = STAGE_KEYS[i];
    const s = status[key] ?? "idle";
    if (s !== "done" && s !== "stale") return false;
  }
  return true;
}

export function RunProvider({ children }: { children: ReactNode }) {
  const [runId, setRunId] = useState<string | null>(null);
  const [manifest, setManifestState] = useState<Manifest | null>(null);
  const [step, setStepState] = useState(0);

  const setManifest = useCallback((m: Manifest) => {
    setManifestState(m);
    setRunId(m.run_id);
  }, []);

  const refresh = useCallback(async () => {
    if (!runId) return;
    const m = await getRun(runId);
    setManifest(m);
  }, [runId, setManifest]);

  const setStep = useCallback(
    (n: number) => {
      if (!isStepEnabled(n, runId, manifest?.stage_status)) return;
      setStepState(n);
    },
    [runId, manifest?.stage_status],
  );

  const value = useMemo(
    () => ({
      runId,
      manifest,
      step,
      setStep,
      refresh,
      setManifest,
    }),
    [runId, manifest, step, setStep, refresh, setManifest],
  );

  return createElement(RunContext.Provider, { value }, children);
}

export function useRun(): RunState {
  const ctx = useContext(RunContext);
  if (!ctx) {
    throw new Error("useRun must be used within RunProvider");
  }
  return ctx;
}
