import type { EvalSectionState } from "../hooks/useEvalSection";
import { percent, ratio, ratioTone } from "../thresholds";
import type { RetrievalRun } from "../types";
import { CategoryBars } from "./CategoryBars";
import { MetricCard } from "./MetricCard";
import { SectionHeader } from "./SectionHeader";

interface Props {
  state: EvalSectionState<RetrievalRun>;
  busy: boolean;
}

/** RAG evaluation: the knowledge-base tool's ranking for each question. */
export function RetrievalSection({ state, busy }: Props) {
  const { run, job, error, start } = state;
  return (
    <section className="eval-section">
      <SectionHeader
        title="RAG evaluation"
        description="The knowledge tool's top results for each question, checked against the expected keywords and source documents. No LLM involved."
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
              <MetricCard label="Mean Reciprocal Rank" value={ratio(run.summary.mrr)} tone={ratioTone(run.summary.mrr)} />
              <MetricCard label="nDCG" value={ratio(run.summary.ndcg)} tone={ratioTone(run.summary.ndcg)} />
              <MetricCard
                label="Keyword coverage"
                value={percent(run.summary.keyword_coverage)}
                tone={ratioTone(run.summary.keyword_coverage)}
              />
              <MetricCard
                label="Source hit"
                value={percent(run.summary.source_hit)}
                tone={ratioTone(run.summary.source_hit)}
                hint={`${run.summary.cases} cases`}
              />
            </div>
            <CategoryBars
              title="Average MRR by category"
              bars={Object.entries(run.by_category).map(([category, s]) => ({ category, value: s.mrr }))}
              max={1}
              format={ratio}
              tone={ratioTone}
            />
          </div>
          <table className="cases">
            <thead>
              <tr>
                <th>Case</th>
                <th>MRR</th>
                <th>Keywords</th>
                <th>Retrieved (rank order)</th>
              </tr>
            </thead>
            <tbody>
              {[...run.results]
                .sort((a, b) => a.retrieval.mrr - b.retrieval.mrr)
                .map(({ case: c, retrieval: r }) => (
                  <tr key={c.id}>
                    <td>
                      <details>
                        <summary>
                          <code>{c.id}</code>
                        </summary>
                        <p>{c.question}</p>
                        <p className="cases__muted">Expected: {c.expected_sources.join(", ")}</p>
                      </details>
                    </td>
                    <td className={`cases__score cases__score--${ratioTone(r.mrr)}`}>{ratio(r.mrr)}</td>
                    <td>
                      {r.keywords_found}/{r.total_keywords}
                    </td>
                    <td>
                      <ol className="cases__sources">
                        {r.sources.map((s) => (
                          <li key={s}>{s}</li>
                        ))}
                      </ol>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
