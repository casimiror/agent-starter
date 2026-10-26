import type { EvalJob, EvalRun } from "../types";

interface Props {
  title: string;
  description: string;
  run: EvalRun | null;
  job: EvalJob | null;
  error: string | null;
  busy: boolean; // any section running: one evaluation at a time
  onRun: () => void;
}

export function SectionHeader({ title, description, run, job, error, busy, onRun }: Props) {
  return (
    <header className="eval-section__header">
      <div>
        <h2 className="eval-section__title">{title}</h2>
        <p className="eval-section__description">{description}</p>
        {run && (
          <p className="eval-section__meta">
            Last run {new Date(run.finished_at).toLocaleString()} · <code>{run.id}</code>
            {run.kind === "answer" && ` · bot ${run.bot_model} · judge ${run.judge_model}`}
            {run.langfuse_url && (
              <>
                {" · "}
                <a href={run.langfuse_url} target="_blank" rel="noopener noreferrer">
                  Langfuse experiment
                </a>
              </>
            )}
          </p>
        )}
      </div>
      <div className="eval-section__actions">
        <button type="button" className="eval-button" onClick={onRun} disabled={busy}>
          {job ? "Running…" : "Run evaluation"}
        </button>
        {job && (
          <div className="progress" role="progressbar" aria-valuenow={job.done} aria-valuemax={job.total}>
            <span className="progress__fill" style={{ width: `${(job.done / Math.max(job.total, 1)) * 100}%` }} />
            <span className="progress__label">
              {job.done}/{job.total}
            </span>
          </div>
        )}
      </div>
      {error && (
        <p className="eval-section__error" role="alert">
          {error}
        </p>
      )}
    </header>
  );
}
