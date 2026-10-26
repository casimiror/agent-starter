import { useCallback, useEffect, useState } from "react";
import { EvalApiError, EvalDisabledError, getJob, getRun, listRuns, startRun } from "../api/evalClient";
import type { EvalJob, EvalKind, EvalRun } from "../types";

const POLL_MS = 1000;

/** One dashboard section: its latest run, a running job's progress, and how to start one. */
export function useEvalSection<R extends EvalRun>(kind: EvalKind) {
  const [run, setRun] = useState<R | null>(null);
  const [job, setJob] = useState<EvalJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [loading, setLoading] = useState(true);

  const fail = (e: unknown) =>
    setError(e instanceof EvalApiError ? e.message : "Network error. Is the API running?");

  // The latest run of this kind, so the page shows results before anything is run.
  useEffect(() => {
    let cancelled = false;
    listRuns(kind)
      .then(async (runs) => {
        if (runs.length && !cancelled) setRun((await getRun(runs[0].id)) as R);
      })
      .catch((e) => (e instanceof EvalDisabledError ? setDisabled(true) : fail(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [kind]);

  // Poll the running job; on success load its run.
  useEffect(() => {
    if (!job || job.status !== "running") return;
    const timer = setTimeout(async () => {
      try {
        const next = await getJob(job.id);
        if (next.status === "done" && next.run_id) {
          setRun((await getRun(next.run_id)) as R);
          setJob(null);
        } else if (next.status === "failed") {
          setError(`The evaluation failed: ${next.error ?? "unknown error"}`);
          setJob(null);
        } else {
          setJob(next);
        }
      } catch (e) {
        fail(e);
        setJob(null);
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [job]);

  const start = useCallback(async () => {
    setError(null);
    try {
      setJob(await startRun(kind));
    } catch (e) {
      fail(e);
    }
  }, [kind]);

  return { run, job, error, disabled, loading, start };
}

export type EvalSectionState<R extends EvalRun> = ReturnType<typeof useEvalSection<R>>;
