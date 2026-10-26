import { Fragment, useState } from "react";
import type { EvalSectionState } from "../hooks/useEvalSection";
import { percent, ratioTone, score, scoreTone } from "../thresholds";
import type { AnswerRun } from "../types";
import { CategoryBars } from "./CategoryBars";
import { MetricCard } from "./MetricCard";
import { SectionHeader } from "./SectionHeader";

interface Props {
  state: EvalSectionState<AnswerRun>;
  busy: boolean;
}

const JUDGE_LABELS: Record<string, string> = {
  accuracy: "Accuracy",
  completeness: "Completeness",
  relevance: "Relevance",
  groundedness: "Groundedness",
  behavior: "Behaviour",
};

/** LLM evaluation: the real agent answers; checks and an LLM judge score the reply. */
export function AnswerSection({ state, busy }: Props) {
  const { run, job, error, start } = state;
  const [onlyFailing, setOnlyFailing] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const results = run ? run.results.filter((r) => !onlyFailing || !r.passed) : [];

  return (
    <section className="eval-section">
      <SectionHeader
        title="LLM evaluation"
        description="The real agent answers every question; deterministic checks and an LLM judge score each reply from 1 to 5."
        run={run}
        job={job}
        error={error}
        busy={busy}
        onRun={start}
      />
      {run && (
        <>
          <div className="eval-section__body">
            <div className="metrics">
              <MetricCard
                label="Pass rate"
                value={percent(run.summary.pass_rate)}
                tone={ratioTone(run.summary.pass_rate)}
                hint={`${run.summary.cases} cases`}
              />
              {Object.entries(run.summary.judge).map(([key, value]) => (
                <MetricCard key={key} label={JUDGE_LABELS[key] ?? key} value={score(value)} tone={scoreTone(value)} />
              ))}
            </div>
            <CategoryBars
              title="Average accuracy by category"
              bars={Object.entries(run.by_category).map(([category, s]) => ({
                category,
                value: s.judge.accuracy ?? 0,
              }))}
              min={1}
              max={5}
              format={(v) => v.toFixed(2)}
              tone={scoreTone}
            />
          </div>
          <div className="cases__toolbar">
            <label>
              <input type="checkbox" checked={onlyFailing} onChange={(e) => setOnlyFailing(e.target.checked)} /> Only
              failing cases ({run.results.filter((r) => !r.passed).length})
            </label>
          </div>
          <table className="cases">
            <thead>
              <tr>
                <th>Case</th>
                <th>Result</th>
                <th>Accuracy</th>
                <th>Behaviour</th>
                <th>Judge feedback</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => {
                const open = expanded.has(r.case.id);
                return (
                  <Fragment key={r.case.id}>
                    <tr>
                      <td>
                        <button
                          type="button"
                          className="cases__toggle"
                          aria-expanded={open}
                          onClick={() => toggle(r.case.id)}
                        >
                          {open ? "▾" : "▸"} <code>{r.case.id}</code>
                        </button>
                      </td>
                      <td>
                        <span className={`badge badge--${r.passed ? "good" : "bad"}`}>{r.passed ? "pass" : "fail"}</span>
                      </td>
                      <td className={`cases__score cases__score--${r.judge ? scoreTone(r.judge.accuracy) : "bad"}`}>
                        {r.judge?.accuracy ?? "–"}
                      </td>
                      <td className={`cases__score cases__score--${r.judge ? scoreTone(r.judge.behavior) : "bad"}`}>
                        {r.judge?.behavior ?? "–"}
                      </td>
                      <td className="cases__feedback">{r.judge?.feedback ?? r.judge_error ?? "No judge result"}</td>
                    </tr>
                    {open && (
                      <tr className="cases__detail">
                        <td colSpan={5}>
                          <p>
                            <strong>Question:</strong> {r.case.question}
                          </p>
                          <p>
                            <strong>Expected ({r.case.expected_behavior}):</strong> {r.case.reference_answer}
                          </p>
                          <p className="cases__reply">
                            <strong>Reply:</strong> {r.reply}
                          </p>
                          <p className="cases__muted">
                            Tools: {r.tool_calls.map((t) => t.name).join(", ") || "none"}
                            {r.blocked_by && ` · blocked by ${r.blocked_by}`} · {r.latency_s.toFixed(1)} s
                            {r.agent_retrieval && ` · retrieved: ${r.agent_retrieval.sources.join(" | ")}`}
                          </p>
                          {r.checks
                            .filter((c) => !c.passed)
                            .map((c) => (
                              <p key={c.name} className="cases__fail">
                                Check failed: {c.name} {c.detail && `(${c.detail})`}
                              </p>
                            ))}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
