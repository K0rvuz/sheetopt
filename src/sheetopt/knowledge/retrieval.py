"""Small deterministic, versioned RAG over curated official Google Sheets references.

No live scraping, external embeddings, database calls or API access.
Retrieved advice is source-attributed and must never be treated as executable.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

_LIBRARY = Path(__file__).resolve().parent / "sources.json"
_TOKENS = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_STOP = {"de", "da", "do", "a", "o", "para", "em", "and", "the", "com", "uma", "por"}


def _terms(text: str) -> set[str]:
    raw = unicodedata.normalize("NFKD", text.lower())
    normal = "".join(c for c in raw if not unicodedata.combining(c))
    return {t for t in _TOKENS.findall(normal) if len(t) > 2 and t not in _STOP}


@lru_cache(maxsize=1)
def all_documents() -> list[dict[str, Any]]:
    """Packaged offline KB; every entry has a traceable authoritative URL."""
    payload = json.loads(_LIBRARY.read_text(encoding="utf-8"))
    documents = payload["documents"]
    for entry in documents:
        if not entry["url"].startswith((
            "https://support.google.com/docs/",
            "https://developers.google.com/workspace/sheets/",
        )):
            raise ValueError("Knowledge source is not in the curated allowlist.")
        if len(entry["guidance"]) > 1000:
            raise ValueError("Knowledge snippet exceeds permitted length.")
    return documents


def search_knowledge(query: str, *, limit: int = 4) -> list[dict[str, str]]:
    """Rank concise snippets by keyword overlap; empty query returns nothing."""
    if not 1 <= limit <= 8 or len(query) > 2000:
        raise ValueError("Unsupported knowledge search.")
    wanted = _terms(query)
    if not wanted:
        return []
    ranked = []
    for doc in all_documents():
        tags = _terms(" ".join(doc["keywords"]))
        title = _terms(doc["title"])
        detail = _terms(doc["guidance"])
        score = 6 * len(wanted & tags) + 3 * len(wanted & title) + len(wanted & detail)
        if score > 0:
            ranked.append((score, doc["id"], doc))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [
        {
            "source_id": doc["id"],
            "title": doc["title"],
            "guidance": doc["guidance"],
            "source_url": doc["url"],
        }
        for _, _, doc in ranked[:limit]
    ]


def knowledge_for_diagnostic(
    function_counts: dict[str, int],
    finding_counts: dict[str, int],
    *,
    focus: str | None = None,
) -> list[dict[str, str]]:
    """Retrieve from a controlled vocabulary, not from private formula text."""
    keywords = []
    for name, value in sorted(function_counts.items(), key=lambda row: -row[1])[:5]:
        if value > 0:
            keywords.append(name)
    if finding_counts.get("PERF-003", 0):
        keywords += ["intervalo", "colunas"]
    if finding_counts.get("PERF-002", 0):
        keywords += ["sumifs", "query"]
    if focus:
        # Sheet names can be sensitive; they are NOT used for RAG retrieval.
        keywords += ["dependencias"]
    return search_knowledge(" ".join(keywords) or "performance", limit=4)
