"""Versioned, source-traceable Google Sheets facts for retrieval and later SFT.

Facts are short, authored summaries, not copied full Google documentation.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sheetopt.knowledge.retrieval import all_documents

_INDEX = Path(__file__).with_name("rules.json")
_TOKEN = re.compile(r"[a-zA-Z0-9_]+", re.ASCII)


@lru_cache(maxsize=1)
def knowledge_rules() -> list[dict[str, Any]]:
    payload = json.loads(_INDEX.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported knowledge rule schema.")
    sources = {doc["id"] for doc in all_documents()}
    seen: set[str] = set()
    for rule in payload["documents"]:
        key = rule["id"]
        host = urlsplit(rule["url"]).hostname
        if key in seen or not re.fullmatch(r"GS-[A-Z0-9-]+", key):
            raise ValueError("Invalid or duplicate rule identifier.")
        if rule["source_id"] not in sources or host not in {
            "support.google.com", "developers.google.com"
        }:
            raise ValueError("Unverified Google Sheets source reference.")
        if len(rule["claim"]) > 400 or not rule.get("requires"):
            raise ValueError("Missing or unbounded factual grounding.")
        seen.add(key)
    return payload["documents"]


def retrieve_rules(terms: set[str], *, limit: int = 5) -> list[dict[str, Any]]:
    """Bounded exact tag matching; never use private sheet names as search terms."""
    if not 1 <= limit <= 12:
        raise ValueError("Invalid retrieval limit.")
    wanted = {w.lower() for w in terms if isinstance(w, str)}
    scored = []
    for rule in knowledge_rules():
        tags = {tag.lower() for tag in rule["tags"]}
        score = len(tags & wanted)
        if score:
            scored.append((score, rule["id"], rule))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [dict(item[2]) for item in scored[:limit]]
