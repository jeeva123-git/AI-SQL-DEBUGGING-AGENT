"""Optional LLM layer (Anthropic API). Everything degrades gracefully without it.

Used for (1) repairing queries the rules cannot fix and (2) writing a plain-English
explanation of what was wrong. Requires:  pip install anthropic  and ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import json
import os
import re

MODEL = os.environ.get("SQL_AGENT_MODEL", "claude-sonnet-4-6")

FIX_SYSTEM = (
    "You are an expert SQL debugger. Given a database schema, a broken SQL query and the error "
    "message from the database engine, return ONLY a JSON object with keys "
    '"fixed_sql" (the corrected query, SQLite dialect, minimal changes) and '
    '"explanation" (2-4 sentences, beginner friendly, naming each mistake and why the fix works). '
    "No markdown, no extra text."
)
EXPLAIN_SYSTEM = (
    "You are a friendly SQL tutor. Given a schema, an original query, a corrected query and a list of "
    "detected issues, explain in 3-5 short sentences what was wrong and the database concept behind it. "
    "Plain text only."
)


def available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def _ask(system: str, user: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=MODEL, max_tokens=1000, system=system,
                                 messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def llm_fix(sql: str, ddl: str, error: str):
    """Return {'fixed_sql', 'explanation'} or None."""
    if not available():
        return None
    try:
        raw = _ask(FIX_SYSTEM, f"Schema:\n{ddl}\n\nQuery:\n{sql}\n\nDatabase error:\n{error}")
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        data = json.loads(raw)
        if isinstance(data.get("fixed_sql"), str):
            return data
    except Exception:
        return None
    return None


def llm_explain(original: str, fixed: str, issues: list, ddl: str):
    """Return a plain-English explanation string or None."""
    if not available():
        return None
    try:
        listing = "\n".join(f"- {i.message}" for i in issues) or "- (none)"
        return _ask(EXPLAIN_SYSTEM, f"Schema:\n{ddl}\n\nOriginal:\n{original}\n\nCorrected:\n{fixed}\n\nIssues:\n{listing}").strip()
    except Exception:
        return None
