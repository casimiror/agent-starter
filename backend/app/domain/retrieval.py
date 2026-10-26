"""What a knowledge search returns, shared by the knowledge tool and the RAG evaluation.

The knowledge tool is named KNOWLEDGE_TOOL and renders its results with `render_docs`; the LLM
evaluation parses them back with `parse_docs` to score what the agent retrieved.
"""

import re
from dataclasses import dataclass
from typing import Protocol

KNOWLEDGE_TOOL = "search_knowledge"
_HEADER = re.compile(r"^\[(?P<source>[^\]›]+?) › (?P<title>[^\]]+)\]$", re.MULTILINE)


@dataclass(frozen=True)
class RetrievedDoc:
    source: str  # document id, e.g. the knowledge file stem
    title: str  # section heading
    text: str


class Retriever(Protocol):
    """The search behind the knowledge tool: its top results for a query, best first."""

    def search(self, query: str) -> list[RetrievedDoc]: ...


def render_docs(docs: list[RetrievedDoc]) -> str:
    return "\n\n".join(f"[{d.source} › {d.title}]\n{d.text}" for d in docs)


def parse_docs(output: str) -> list[RetrievedDoc]:
    """Split a knowledge tool result back into the documents `render_docs` rendered."""
    matches = list(_HEADER.finditer(output))
    docs = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(output)
        body = output[match.end() : end].strip()
        docs.append(RetrievedDoc(match["source"].strip(), match["title"].strip(), body))
    return docs
