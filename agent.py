"""The debugging agent: analyze -> repair -> validate -> explain."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import llm
from .rules import LOGIC_RULES, SYNTAX_RULES, Issue, repair_from_error
from .schema import Schema

MAX_REPAIR_ROUNDS = 6


@dataclass
class DebugResult:
    original: str
    fixed: str
    valid: bool
    issues: list = field(default_factory=list)
    explanation: str = ""
    remaining_error: str = ""
    used_llm: bool = False
    preview: tuple | None = None   # (columns, rows)

    def to_dict(self) -> dict:
        return {"original": self.original, "fixed": self.fixed, "valid": self.valid,
                "issues": [i.as_dict() for i in self.issues], "explanation": self.explanation,
                "remaining_error": self.remaining_error, "used_llm": self.used_llm}


class DebugAgent:
    def __init__(self, schema: Schema, use_llm: bool = True):
        self.schema = schema
        self.use_llm = use_llm and llm.available()

    # ------------------------------------------------------------------
    def debug(self, sql: str) -> DebugResult:
        original = sql
        current = sql.strip().rstrip(";").strip()
        issues: list[Issue] = []

        # Stage 1: syntax rules (typos, quotes, commas, operators)
        for rule in SYNTAX_RULES:
            current, found = rule(current, self.schema)
            issues += found

        # Stage 2: let the real engine report bad names, repair them, then run the
        # logic rules (joins, GROUP BY, HAVING) on a query whose names are now correct
        current, error = self._repair_names(current, issues)
        for rule in LOGIC_RULES:
            current, found = rule(current, self.schema)
            issues += found
        current, error = self._repair_names(current, issues)

        # Stage 3: LLM fallback for anything the rules could not solve
        used_llm, llm_note = False, ""
        if error and self.use_llm:
            data = llm.llm_fix(current, self.schema.ddl, error)
            if data:
                candidate = data["fixed_sql"].strip().rstrip(";")
                if self.schema.validate(candidate) is None:
                    issues.append(Issue("syntax", "error", "Repaired by the language model: " + error,
                                        current, candidate))
                    current, error, used_llm = candidate, None, True
                    llm_note = data.get("explanation", "")

        valid = error is None
        result = DebugResult(original=original, fixed=current + ";", valid=valid, issues=issues,
                             remaining_error=error or "", used_llm=used_llm)
        if valid:
            result.preview = self.schema.preview(current)
        result.explanation = self._explain(result, llm_note)
        return result

    def _repair_names(self, sql: str, issues: list):
        error = self.schema.validate(sql)
        for _ in range(MAX_REPAIR_ROUNDS):
            if not error:
                break
            new, found = repair_from_error(sql, error, self.schema)
            issues += found
            if not new or new == sql:
                break
            sql, error = new, self.schema.validate(new)
        return sql, error

    # ------------------------------------------------------------------
    def _explain(self, r: DebugResult, llm_note: str) -> str:
        if self.use_llm and r.issues:
            text = llm.llm_explain(r.original, r.fixed, r.issues, self.schema.ddl)
            if text:
                return text
        if llm_note:
            return llm_note
        if not r.issues:
            return ("No problems found: the query is valid for this schema." if r.valid
                    else f"The database still reports an error I could not fix automatically: {r.remaining_error}")
        lines = []
        for i, issue in enumerate(r.issues, 1):
            line = f"{i}. {issue.message}"
            if issue.concept:
                line += f" Why: {issue.concept}"
            lines.append(line)
        if not r.valid:
            lines.append(f"Still failing: {r.remaining_error}. Check table/column names against the schema.")
        return "\n".join(lines)


def format_report(r: DebugResult) -> str:
    """Plain-text report for the CLI."""
    icon = {"error": "[ERROR]", "warning": "[WARN] ", "info": "[INFO] "}
    out = ["ORIGINAL QUERY", "  " + r.original.strip(), "", "CORRECTED QUERY", "  " + r.fixed, ""]
    out.append("STATUS: " + ("valid against schema" if r.valid else "STILL INVALID - " + r.remaining_error))
    if r.issues:
        out += ["", "ISSUES FOUND"]
        out += [f"  {icon.get(i.severity, '')} {i.message}" for i in r.issues]
    out += ["", "EXPLANATION", *("  " + ln for ln in r.explanation.splitlines())]
    if r.preview:
        cols, rows = r.preview
        out += ["", "RESULT PREVIEW", "  " + " | ".join(cols)]
        out += ["  " + " | ".join(str(v) for v in row) for row in rows] or ["  (no rows)"]
    return "\n".join(out)
