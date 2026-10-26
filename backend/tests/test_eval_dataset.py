import re

import pytest

from app.core.config import Settings
from app.evals.agent_run import eval_tool_deps
from app.evals.dataset import load_dataset
from app.tools.registry import build_assistant_tools, build_retriever

CASES = load_dataset()
SETTINGS = Settings(_env_file=None)
TOOLS = {tool.name for tool in build_assistant_tools(eval_tool_deps(SETTINGS))}
RETRIEVER = build_retriever(eval_tool_deps(SETTINGS))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def test_ids_are_unique():
    assert len({c.id for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_expected_tools_exist(case):
    assert set(case.expected_tools) <= TOOLS


@pytest.mark.parametrize("case", [c for c in CASES if c.keywords], ids=lambda c: c.id)
def test_keywords_are_retrievable_from_expected_sources(case):
    """Keeps the dataset honest when the knowledge changes: every keyword is in one of its
    expected sources, as the knowledge tool returns them."""
    assert RETRIEVER is not None, "cases with keywords need a knowledge tool"
    assert case.expected_sources, "keywords need the documents they come from"
    found = RETRIEVER.search(case.question) + [
        doc for kw in case.keywords for doc in RETRIEVER.search(kw)
    ]
    text = " ".join(_normalize(d.text) for d in found if d.source in case.expected_sources)
    missing = [k for k in case.keywords if _normalize(k) not in text]
    assert not missing, f"not in {case.expected_sources}: {missing}"
