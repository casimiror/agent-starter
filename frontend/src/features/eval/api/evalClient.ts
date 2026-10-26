import type { EvalCapabilities, EvalJob, EvalKind, EvalRun, EvalRunItem } from "../types";

/** The API answers 404 when EVAL_ENABLED is off (the deployed app). */
export class EvalDisabledError extends Error {}

export class EvalApiError extends Error {}

// The only place that knows the /api/evals contract.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/evals${path}`, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
  });
  // The list endpoint always exists when the feature is on, so a 404 there means "off".
  if (res.status === 404 && path.startsWith("/runs?")) throw new EvalDisabledError();
  if (res.status === 409) throw new EvalApiError("Another evaluation is already running.");
  if (!res.ok) throw new EvalApiError(`The evaluation API failed (${res.status}).`);
  return res.json() as Promise<T>;
}

export const listRuns = (kind: EvalKind) => request<EvalRunItem[]>(`/runs?kind=${kind}`);

export const getRun = (id: string) => request<EvalRun>(`/runs/${encodeURIComponent(id)}`);

export const startRun = (kind: EvalKind) =>
  request<EvalJob>("/runs", { method: "POST", body: JSON.stringify({ kind }) });

export const getJob = (id: string) => request<EvalJob>(`/jobs/${encodeURIComponent(id)}`);

/** What this project can evaluate: the RAG evaluation needs a knowledge tool. */
export const getCapabilities = () => request<EvalCapabilities>("/capabilities");
