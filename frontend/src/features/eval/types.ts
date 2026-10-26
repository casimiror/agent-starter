// Mirrors backend app/evals/results.py and app/schemas/evals.py

export type EvalKind = "retrieval" | "answer";

export interface EvalCase {
  id: string;
  category: string;
  scenario: number | null;
  language: string;
  question: string;
  keywords: string[];
  expected_sources: string[];
  reference_answer: string;
  expected_behavior: string;
  expected_tools: string[];
  forbidden_tools?: string[];
  forbidden: string[];
}

export interface RetrievalMetrics {
  mrr: number;
  ndcg: number;
  keyword_coverage: number;
  keywords_found: number;
  total_keywords: number;
  source_hit: boolean;
  sources: string[];
}

export interface Check {
  name: string;
  passed: boolean;
  detail: string;
}

export interface JudgeScores {
  feedback: string;
  accuracy: number;
  completeness: number;
  relevance: number;
  groundedness: number;
  behavior: number;
}

export interface RetrievalCaseResult {
  case: EvalCase;
  retrieval: RetrievalMetrics;
}

export interface AnswerCaseResult {
  case: EvalCase;
  reply: string;
  blocked_by: string | null;
  tool_calls: { name: string; args: Record<string, unknown> }[];
  agent_retrieval: RetrievalMetrics | null;
  checks: Check[];
  judge: JudgeScores | null;
  judge_error: string | null;
  latency_s: number;
  trace_id: string | null;
  passed: boolean;
}

export interface RetrievalSummary {
  cases: number;
  mrr: number;
  ndcg: number;
  keyword_coverage: number;
  source_hit: number;
}

export interface AnswerSummary {
  cases: number;
  pass_rate: number;
  checks_pass_rate: number;
  judge: Record<string, number>;
  agent_retrieval: Record<string, number>;
  latency_s: number;
}

interface RunBase {
  id: string;
  started_at: string;
  finished_at: string;
  langfuse_url: string | null;
}

export interface RetrievalRun extends RunBase {
  kind: "retrieval";
  summary: RetrievalSummary;
  by_category: Record<string, RetrievalSummary>;
  results: RetrievalCaseResult[];
}

export interface AnswerRun extends RunBase {
  kind: "answer";
  bot_model: string;
  judge_model: string;
  summary: AnswerSummary;
  by_category: Record<string, AnswerSummary>;
  results: AnswerCaseResult[];
}

export type EvalRun = RetrievalRun | AnswerRun;

export interface EvalJob {
  id: string;
  kind: EvalKind;
  status: "running" | "done" | "failed";
  done: number;
  total: number;
  run_id: string | null;
  error: string | null;
}

export interface EvalRunItem {
  id: string;
  kind: EvalKind;
  started_at: string;
  finished_at: string;
  langfuse_url: string | null;
}

export interface EvalCapabilities {
  retrieval: boolean;
}
