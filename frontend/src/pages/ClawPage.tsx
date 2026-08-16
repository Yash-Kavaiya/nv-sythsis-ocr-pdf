import { useState } from "react";
import ClawRail from "../components/ClawRail";
import { useRun } from "../state/runStore";

type ActivityEntry = {
  id: number;
  type: string;
  detail: string;
  at: string;
};

export default function ClawPage() {
  const { runId } = useRun();
  const [activity, setActivity] = useState<ActivityEntry[]>([]);

  function logActivity(entry: { type: string; detail: string }) {
    setActivity((prev) => [
      ...prev,
      {
        id: Date.now() + prev.length,
        type: entry.type,
        detail: entry.detail,
        at: new Date().toLocaleTimeString(),
      },
    ]);
  }

  if (!runId) {
    return (
      <div className="page">
        <h1>NeMo Claw</h1>
        <div className="error-box">Create a run to chat with NeMo Claw.</div>
      </div>
    );
  }

  return (
    <div className="page claw-page">
      <h1>NeMo Claw</h1>
      <p className="subtitle">
        Orchestrate the pipeline — ask about failures, re-run stages, or inspect reports.
      </p>

      <div className="claw-layout">
        <div className="claw-main">
          <ClawRail runId={runId} compact={false} onActivity={logActivity} />
        </div>
        <div className="card activity-log">
          <h2>Activity log</h2>
          {activity.length === 0 ? (
            <p className="hint">Tool calls and replies appear here.</p>
          ) : (
            <ul className="activity-list">
              {activity.map((entry) => (
                <li key={entry.id}>
                  <span className="activity-time">{entry.at}</span>
                  <span className="activity-type">{entry.type}</span>
                  <span className="activity-detail">{entry.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
