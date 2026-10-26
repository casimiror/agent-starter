# Recipe: knowledge-search

The agent answers from documents the project curates (product docs, FAQ, policies). Markdown files
split by `## ` headings, ranked with BM25. Keyword search on purpose: small corpus, easy to debug;
revisit (hybrid or pgvector) past ~50 documents. Adding it also turns on the **RAG evaluation**.

The tool must be named `search_knowledge` (`KNOWLEDGE_TOOL`) and render results with
`render_docs`: that is how the evaluator reads what the agent retrieved.

## Files

### `backend/app/knowledge/<topic>.md` (one file per topic)

```markdown
# <Topic>
<!-- Source: <where this content comes from, and its date>. Not indexed (before the first ##). -->

## <Heading with the words people search with>
<100-250 words, self-contained: one retrievable chunk.>
```

Rules for the content (also in `docs/knowledge-base.md`):
- Each `## ` section is one chunk: self-contained, at most about 250 words. Short is fine when
  the facts are short: never pad a section with details that are not in the sources (the agent
  repeats them as facts).
- Put the words users search with in the heading (titles weigh 3x).
- No raw URLs and no `$` amounts if those guardrails are on: the whole reply would be replaced.
  Links come from `ALLOWED_LINKS` through tools.
- One language (the tool asks the model for keywords in it).

### `backend/app/tools/knowledge/kb.py`

```python
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.retrieval import RetrievedDoc

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"
_WORD = re.compile(r"[a-z0-9]+")
# Words that appear in nearly every section and only add noise to the ranking.
_STOPWORDS = {
    "the", "and", "for", "you", "your", "are", "with", "that", "this", "what", "how", "can",
    "from", "our", "into", "not", "who", "when", "which", "they", "their",
}  # fmt: skip
# BM25 parameters (standard defaults) and how much a title match outweighs a body match.
_K1, _B, _TITLE_WEIGHT = 1.5, 0.75, 3


def _stem(word: str) -> str:
    """Fold plurals so "policies" matches "policy" and "agents" matches "agent"."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _tokens(text: str) -> list[str]:
    words = _WORD.findall(text.lower())
    return [_stem(w) for w in words if len(w) > 2 and w not in _STOPWORDS]


@dataclass(frozen=True)
class Section:
    source: str
    title: str
    body: str
    terms: Counter[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        terms = Counter(_tokens(self.body))
        for word in _tokens(self.title):
            terms[word] += _TITLE_WEIGHT
        object.__setattr__(self, "terms", terms)

    @property
    def length(self) -> int:
        return sum(self.terms.values())

    def as_doc(self) -> RetrievedDoc:
        return RetrievedDoc(self.source, self.title, self.body.strip())


class KnowledgeBase:
    """Markdown files split by `## ` headings, ranked with BM25 (title words weigh more).

    Implements `Retriever` (app/domain/retrieval.py), so the RAG evaluation uses this same search.
    """

    def __init__(self, directory: Path = KNOWLEDGE_DIR) -> None:
        self.sections = [s for path in sorted(directory.glob("*.md")) for s in self._split(path)]
        doc_freq = Counter(word for s in self.sections for word in s.terms)
        n = len(self.sections)
        self._idf = {w: math.log(1 + (n - df + 0.5) / (df + 0.5)) for w, df in doc_freq.items()}
        self._avg_len = sum(s.length for s in self.sections) / n if n else 0.0

    @staticmethod
    def _split(path: Path) -> list[Section]:
        parts = re.split(r"^## ", path.read_text(), flags=re.MULTILINE)
        sections = []
        for part in parts[1:]:
            title, _, body = part.partition("\n")
            sections.append(Section(source=path.stem, title=title.strip(), body=body))
        return sections

    def _score(self, query: set[str], section: Section) -> float:
        norm = _K1 * (1 - _B + _B * section.length / self._avg_len)
        score = 0.0
        for word in query:
            tf = section.terms.get(word, 0)
            if tf:
                score += self._idf[word] * tf * (_K1 + 1) / (tf + norm)
        return score

    def search(self, query: str, k: int = 3) -> list[RetrievedDoc]:
        q = set(_tokens(query))
        scored = [(self._score(q, s), s) for s in self.sections]
        ranked = [s for score, s in sorted(scored, key=lambda x: -x[0]) if score > 0]
        return [s.as_doc() for s in ranked[:k]]
```

The tokenizer only keeps `[a-z0-9]`: for a corpus in a language with accents, normalize them first
(`unicodedata.normalize("NFKD", text).encode("ascii", "ignore")`) in `_tokens`.

### `backend/app/tools/knowledge/search_knowledge.py`

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.domain.retrieval import KNOWLEDGE_TOOL, render_docs
from app.tools.builder import ToolBuilder
from app.tools.knowledge.kb import KnowledgeBase


class SearchKnowledgeArgs(BaseModel):
    query: str = Field(description="What the user wants to know, as a few <language> keywords")


def build_search_knowledge_tool(kb: KnowledgeBase) -> BaseTool:
    def search(query: str) -> str:
        docs = kb.search(query)
        if not docs:
            return "NO_RESULTS: the knowledge base has nothing on this. <What the agent does then>."
        return render_docs(docs)

    return (
        ToolBuilder(KNOWLEDGE_TOOL)
        .describe(
            "Search <product>'s knowledge base: <the topics it covers>. Always use it before "
            "answering a factual question about <product>; search again with other keywords if "
            "the first results don't answer it."
        )
        .args(SearchKnowledgeArgs)
        .handler(search)
        .build()
    )
```

## Wiring

`app/tools/registry.py` (keep what other tools already added):

```python
from app.tools.knowledge.kb import KnowledgeBase
from app.tools.knowledge.search_knowledge import build_search_knowledge_tool


@dataclass(frozen=True, kw_only=True)
class ToolDeps:
    settings: Settings
    kb: KnowledgeBase


def build_assistant_tools(deps: ToolDeps) -> list[BaseTool]:
    return [build_search_knowledge_tool(deps.kb)]


def build_retriever(deps: ToolDeps) -> Retriever | None:
    """The knowledge tool's search: turns on the RAG evaluation."""
    return deps.kb
```

`ToolDeps` is keyword-only, so its callers name each dependency:

- `app/api/deps.py` `get_tool_deps`: `ToolDeps(settings=get_settings(), kb=KnowledgeBase())`.
- `app/evals/agent_run.py` `eval_tool_deps`: `ToolDeps(settings=settings, kb=KnowledgeBase())`
  (read-only, no stand-in needed).

## Tests: `backend/tests/test_knowledge.py`

```python
import re

import pytest

from app.guardrails.output import AllowedLinksGuardrail, NoInventedPricesGuardrail
from app.tools.knowledge.kb import KNOWLEDGE_DIR, KnowledgeBase
from app.tools.knowledge.search_knowledge import build_search_knowledge_tool


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return KnowledgeBase()


def test_title_match_outranks_passing_mention(tmp_path):
    (tmp_path / "a.md").write_text(
        "# A\n## Pricing\nDepends on scope.\n"
        "## Services\nPricing is mentioned here in passing, along with many other words.\n"
    )
    assert KnowledgeBase(tmp_path).search("pricing")[0].title == "Pricing"


def test_plurals_match_singular(tmp_path):
    (tmp_path / "a.md").write_text("# A\n## Policies\nRefunds within 30 days.\n")
    assert KnowledgeBase(tmp_path).search("policy")


def test_header_before_first_section_is_not_indexed(tmp_path):
    (tmp_path / "a.md").write_text("# A\n<!-- Source: secret notes -->\n## Hours\n9 to 5.\n")
    assert KnowledgeBase(tmp_path).search("secret notes") == []


@pytest.mark.parametrize(("query", "expected"), [("<scenario keywords>", "<file stem>")])
def test_scenario_queries_hit_the_right_document(kb, query, expected):
    assert kb.search(query)[0].source == expected


def test_no_results_code(kb):
    assert build_search_knowledge_tool(kb).invoke({"query": "zzz qqq"}).startswith("NO_RESULTS")


def test_knowledge_passes_output_guardrails():
    # The agent quotes the knowledge verbatim; a raw URL or a "$ 5" would get the reply replaced.
    for path in KNOWLEDGE_DIR.glob("*.md"):
        text = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.DOTALL)
        assert AllowedLinksGuardrail([]).check(text).allowed, path.name
        assert NoInventedPricesGuardrail().check(text).allowed, path.name
```

One `test_scenario_queries_hit_the_right_document` row per `plan.md` scenario the knowledge
answers (or per section, if `plan.md` has no scenarios yet).

## Prompt, evals, docs

- Prompt: "For any factual question about <product>, call `search_knowledge` first and answer only
  from what it returns. If it returns NO_RESULTS, say you don't have that information and <offer
  the escalation path>."
- Eval cases: the course categories (`direct_fact`, `temporal`, `spanning`, `comparative`,
  `numerical`, `relationship`, `holistic`) with `keywords` copied from the files in
  `expected_sources` and `expected_tools: ["search_knowledge"]`. Copy keywords character for
  character (punctuation included: "3-5 business days"); `tests/test_eval_dataset.py` only folds
  case and whitespace. Add one `escalation` case for the NO_RESULTS path (a question the
  knowledge doesn't cover, no keywords, `expected_behavior: "escalate"`,
  `expected_tools: ["search_knowledge"]`).
- `plan.md`: the tool's row in "Agents and tools".
- Docs: create `docs/knowledge-base.md` (sources of each file, the writing rules above, how
  retrieval works, the tests), add it to `CLAUDE.md` (Where to look) and `docs/README.md`, and add
  `.claude/rules/knowledge.md`:

  ```markdown
  ---
  paths:
    - "backend/app/knowledge/**"
  ---
  # Knowledge

  Before editing the knowledge base, read `docs/knowledge-base.md`. Sections are split by `## `,
  self-contained, no raw URLs; then run `make test` (keyword and ranking checks).
  ```
