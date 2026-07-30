export type Manifest = {
  run_id: string;
  stage_status: Record<string, string>;
  stage_error?: { stage: string; error: string; hint: string } | null;
  schema?: Record<string, unknown>;
  docs?: Array<Record<string, unknown>>;
  stages?: Array<{ stage: string; detail: Record<string, unknown> }>;
  request?: Record<string, unknown>;
  llm_backed?: boolean;
};

export type StageResult = { ok: boolean; manifest: Manifest };

export type ClawChatResult = {
  reply: string;
  tool_calls: unknown[];
  messages: unknown[];
};

type StageErrorBody = {
  ok?: boolean;
  stage?: string;
  error?: string;
  hint?: string;
  detail?: string | { msg?: string }[];
};

export class ApiError extends Error {
  status: number;
  stage?: string;
  hint?: string;

  constructor(message: string, status: number, body?: StageErrorBody) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.stage = body?.stage;
    this.hint = body?.hint;
  }
}

function errorMessage(status: number, body: StageErrorBody): string {
  if (body.error) return body.error;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    const first = body.detail[0];
    if (first && typeof first === "object" && "msg" in first) return String(first.msg);
  }
  return `Request failed (${status})`;
}

async function readJson(res: Response): Promise<StageErrorBody> {
  try {
    return (await res.json()) as StageErrorBody;
  } catch {
    return {};
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = await readJson(res);
  if (!res.ok) {
    throw new ApiError(errorMessage(res.status, body), res.status, body);
  }
  return body as T;
}

async function stageRequest(url: string, init?: RequestInit): Promise<StageResult> {
  const res = await fetch(url, init);
  const body = await readJson(res);
  if (!res.ok || body.ok === false) {
    throw new ApiError(errorMessage(res.status, body), res.status, body);
  }
  return body as StageResult;
}

export async function createRun(body: object): Promise<Manifest> {
  return request<Manifest>("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function curate(runId: string, body: object): Promise<StageResult> {
  return stageRequest(`/api/runs/${runId}/curate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function design(runId: string, body: object): Promise<StageResult> {
  return stageRequest(`/api/runs/${runId}/design`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function synthesize(runId: string, body: object): Promise<StageResult> {
  return stageRequest(`/api/runs/${runId}/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function runPipeline(body: object): Promise<Manifest> {
  const res = await fetch("/api/pipeline/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readJson(res);
  if (!res.ok || data.ok === false) {
    throw new ApiError(errorMessage(res.status, data), res.status, data);
  }
  return data as Manifest;
}

export async function clawChat(runId: string, message: string): Promise<ClawChatResult> {
  return request<ClawChatResult>("/api/claw/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, message }),
  });
}

export async function getRun(runId: string): Promise<Manifest> {
  return request<Manifest>(`/api/runs/${runId}`);
}

export async function listRuns(): Promise<unknown[]> {
  return request<unknown[]>("/api/runs");
}

export async function runEval(body: object): Promise<unknown> {
  return request<unknown>("/api/eval/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function health(): Promise<unknown> {
  return request<unknown>("/api/health");
}

export async function hfPreview(
  dataset: string,
  config?: string,
  split = "train",
  limit = 3,
): Promise<{ rows: unknown[]; count: number }> {
  const params = new URLSearchParams({ dataset, split, limit: String(limit) });
  if (config) params.set("config", config);
  return request(`/api/hf/preview?${params}`);
}

export async function samplePreview(): Promise<{ rows: unknown[]; count: number }> {
  return request("/api/sample/preview");
}

export async function listEvals(): Promise<unknown[]> {
  return request<unknown[]>("/api/evals");
}

export async function getEval(evalId: string): Promise<unknown> {
  return request<unknown>(`/api/evals/${evalId}`);
}
