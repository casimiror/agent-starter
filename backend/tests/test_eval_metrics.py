import math

import pytest

from app.domain.retrieval import RetrievedDoc, parse_docs, render_docs
from app.evals.agent_run import AgentRun, ToolCall
from app.evals.checks import run_checks
from app.evals.dataset import EvalCase
from app.evals.retrieval import ndcg, score_retrieval

DOCS = [
    RetrievedDoc("faq", "Hours", "Monday to Friday"),
    RetrievedDoc("company", "Office", "12 Market Street, Springfield"),
]


def _case(**overrides) -> EvalCase:
    base = {
        "id": "x-01",
        "category": "direct_fact",
        "question": "q",
        "keywords": [],
        "expected_sources": [],
        "reference_answer": "r",
        "expected_behavior": "answer",
        "expected_tools": [],
        "forbidden": [],
    }
    return EvalCase.model_validate(base | overrides)


def _run(**overrides) -> AgentRun:
    base = {"reply": "ok", "blocked_by": None, "tool_calls": [], "retrieved": [], "latency_s": 1}
    return AgentRun(**(base | overrides))


def test_retrieval_metrics_follow_rank():
    m = score_retrieval(["Springfield", "Monday", "Madrid"], ["company"], DOCS)
    assert m.mrr == pytest.approx((1 / 2 + 1 + 0) / 3)
    assert m.keywords_found == 2 and m.keyword_coverage == pytest.approx(2 / 3)
    assert m.source_hit
    # Found only at rank 2 of a list with one relevant doc: DCG 1/log2(3), ideal 1.
    assert ndcg("Springfield", DOCS, k=10) == pytest.approx(1 / math.log2(3))


def test_keyword_match_ignores_case_and_line_breaks():
    docs = [RetrievedDoc("services", "t", "a 45-day\nengagement")]
    assert score_retrieval(["45-DAY ENGAGEMENT"], ["services"], docs).mrr == 1


def test_no_keywords_means_no_retrieval_score():
    assert score_retrieval([], [], DOCS) is None


def test_parse_docs_round_trips_rendered_docs():
    docs = [
        RetrievedDoc("faq", "Hours", "Mon-Fri\n\nPacific"),
        RetrievedDoc("company", "Office", "SD"),
    ]
    assert parse_docs(render_docs(docs)) == docs


def test_checks_block_tools_and_forbidden():
    case = _case(expected_behavior="block", forbidden=["$"])
    checks = {c.name: c.passed for c in run_checks(case, _run(reply="It costs $5"))}
    assert checks == {"no_error": True, "blocked": False, "no_forbidden": False}

    case = _case(expected_tools=["send_request"])
    run = _run(tool_calls=[ToolCall(name="send_request", args={})])
    assert all(c.passed for c in run_checks(case, run))


def test_answer_replaced_by_guardrail_fails():
    checks = run_checks(_case(), _run(blocked_by="price in output"))
    assert {c.name: c.passed for c in checks}["not_blocked"] is False


def test_clarify_case_fails_when_the_tool_runs_before_asking():
    case = _case(expected_behavior="clarify", forbidden_tools=["send_request"])
    early = run_checks(case, _run(tool_calls=[ToolCall(name="send_request", args={})]))
    assert {c.name: c.passed for c in early}["not_called:send_request"] is False
    assert all(c.passed for c in run_checks(case, _run(reply="What is your email?")))
