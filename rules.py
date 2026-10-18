"""Rule-based analysis and repair of SQL queries.

Each rule has the signature  rule(sql, schema) -> (new_sql, [Issue]).
Rules only change the query when they are confident about the fix.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

CORE_KEYWORDS = ["SELECT", "FROM", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "JOIN",
                 "INNER", "OUTER", "DISTINCT", "BETWEEN", "UNION"]
FUNCTIONS = ["COUNT", "SUM", "AVG", "MIN", "MAX"]
ALL_KEYWORDS = set(CORE_KEYWORDS + FUNCTIONS + [
    "BY", "ON", "AND", "OR", "NOT", "NULL", "IN", "LIKE", "AS", "ASC", "DESC", "LEFT", "RIGHT",
    "FULL", "CROSS", "NATURAL", "USING", "IS", "EXISTS", "CASE", "WHEN", "THEN", "ELSE", "END",
    "ALL", "ANY", "OFFSET", "INTERSECT", "EXCEPT", "WITH", "TRUE", "FALSE", "CAST", "COALESCE",
    "GROUP_CONCAT", "TOTAL", "INSERT", "INTO", "VALUES", "UPDATE", "SET", "DELETE"])
COMMON_TYPOS = {
    "SELCT": "SELECT", "SLECT": "SELECT", "SELEC": "SELECT", "SELET": "SELECT", "SELECTT": "SELECT",
    "FORM": "FROM", "FRM": "FROM", "FOM": "FROM",
    "WEHRE": "WHERE", "WHRE": "WHERE", "WHER": "WHERE", "WERE": "WHERE",
    "GRUOP": "GROUP", "GORUP": "GROUP", "GROPU": "GROUP",
    "ODER": "ORDER", "ORDRE": "ORDER", "OREDR": "ORDER",
    "JION": "JOIN", "JOINN": "JOIN", "JOING": "JOIN",
    "HAVNG": "HAVING", "HAVIGN": "HAVING", "HAVIN": "HAVING",
    "DISTICT": "DISTINCT", "DISTINT": "DISTINCT", "DISTINC": "DISTINCT",
    "LIMT": "LIMIT", "LIMTI": "LIMIT",
}
MERGED = {"GROUPBY": "GROUP BY", "ORDERBY": "ORDER BY", "INNERJOIN": "INNER JOIN",
          "LEFTJOIN": "LEFT JOIN", "RIGHTJOIN": "RIGHT JOIN"}
CLAUSE_ORDER = ["SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT"]
AGG_RE = re.compile(r"\b(?:COUNT|SUM|AVG|MIN|MAX|TOTAL|GROUP_CONCAT)\s*\(", re.I)
NOT_ALIAS = r"(?!(?:ON|USING|INNER|LEFT|RIGHT|FULL|CROSS|NATURAL|JOIN|WHERE|GROUP|ORDER|HAVING|LIMIT|UNION)\b)"
FROM_RE = re.compile(rf"\b(FROM|JOIN)\s+(\w+)(?:\s+(?:AS\s+)?{NOT_ALIAS}(\w+))?", re.I)


@dataclass
class Issue:
    category: str          # syntax | join | column | table | logic | style
    severity: str          # error | warning | info
    message: str
    before: str = ""
    after: str = ""
    concept: str = ""      # short teaching note

    def as_dict(self):
        return self.__dict__.copy()


# ---------------------------------------------------------------- helpers
def top_mask(s: str) -> list:
    """True for characters outside parentheses and quotes."""
    mask, depth, quote = [], 0, None
    for ch in s:
        if quote:
            mask.append(False)
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            mask.append(False)
        else:
            if ch == "(":
                depth += 1
            mask.append(depth == 0)
            if ch == ")":
                depth = max(0, depth - 1)
    return mask


def mask_strings(s: str) -> str:
    """Blank out quoted text (same length) so regexes ignore literals."""
    out, quote = [], None
    for ch in s:
        if quote:
            out.append(ch if ch == quote else " ")
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            out.append(ch)
        else:
            out.append(ch)
    return "".join(out)


def apply_edits(sql: str, edits: list) -> str:
    for start, end, repl in sorted(edits, reverse=True):
        sql = sql[:start] + repl + sql[end:]
    return sql


def sub_unquoted(sql: str, pattern: str, repl, flags=re.I):
    """Regex substitution that ignores quoted text. Returns (new_sql, n_changes)."""
    edits = []
    for m in re.finditer(pattern, mask_strings(sql), flags):
        r = repl(m) if callable(repl) else m.expand(repl)
        edits.append((m.start(), m.end(), r))
    return apply_edits(sql, edits), len(edits)


def split_top(text: str, sep: str) -> list:
    mask, pieces, last = top_mask(text), [], 0
    for m in re.finditer(sep, text, re.I):
        if mask[m.start()]:
            pieces.append(text[last:m.start()])
            last = m.end()
    pieces.append(text[last:])
    return [p.strip() for p in pieces]


def split_clauses(sql: str):
    """Split a simple top-level query into [(CLAUSE, text)], or None if too complex."""
    s = sql.strip().rstrip(";").strip()
    mask = top_mask(s)
    pat = re.compile(r"\b(SELECT|FROM|WHERE|GROUP\s+BY|HAVING|ORDER\s+BY|LIMIT)\b", re.I)
    hits = [m for m in pat.finditer(s) if mask[m.start()]]
    if not hits or hits[0].start() != 0 or hits[0].group(1).upper() != "SELECT":
        return None
    if any(mask[m.start()] for m in re.finditer(r"\b(UNION|INTERSECT|EXCEPT)\b", s, re.I)):
        return None
    parts = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(s)
        parts.append((re.sub(r"\s+", " ", m.group(1).upper()), s[m.end():end].strip()))
    names = [p[0] for p in parts]
    if len(set(names)) != len(names):
        return None
    return parts


def join_clauses(parts: list) -> str:
    return " ".join(f"{k} {t}".strip() for k, t in parts)


def parse_from(sql: str) -> list:
    """Return [(table, alias_or_None)] for FROM/JOIN items."""
    return [(m.group(2), m.group(3)) for m in FROM_RE.finditer(mask_strings(sql))]


def alias_map(sql: str, schema) -> dict:
    out = {}
    for table, alias in parse_from(sql):
        real = schema.table_name(table) or table
        out[(alias or table).lower()] = real
        out[table.lower()] = real
    return out


def known_identifiers(schema) -> set:
    names = {t.lower() for t in schema.table_names()}
    names |= {c.lower() for c in schema.all_columns()}
    return names


def closest(word: str, candidates: list, cutoff: float = 0.6):
    low = {c.lower(): c for c in candidates}
    hit = difflib.get_close_matches(word.lower(), list(low), n=1, cutoff=cutoff)
    return low[hit[0]] if hit else None


# ------------------------------------------------------------------ rules
def rule_balance(sql, schema):
    issues = []
    if sql.count("'") % 2 == 1:
        sql += "'"
        issues.append(Issue("syntax", "error", "Unclosed string literal; added the missing closing quote.",
                            concept="String values must be wrapped in matching single quotes."))
    masked = mask_strings(sql)
    diff = masked.count("(") - masked.count(")")
    if diff > 0:
        sql = sql.rstrip() + ")" * diff
        issues.append(Issue("syntax", "error", f"{diff} unclosed parenthesis; added at the end of the query.",
                            concept="Every '(' needs a matching ')'. Check that the added bracket is in the right place."))
    elif diff < 0 and sql.rstrip().endswith(")"):
        sql = sql.rstrip()[:diff]
        issues.append(Issue("syntax", "error", "Extra closing parenthesis removed.",
                            concept="Every ')' must close a '(' opened earlier."))
    return sql, issues


def rule_double_quotes(sql, schema):
    """Double quotes are identifiers in standard SQL; string values need single quotes."""
    issues, known = [], known_identifiers(schema)

    def fix(m):
        inner = m.group(1)
        if inner.lower() in known:
            return m.group(0)
        issues.append(Issue("syntax", "error", f'"{inner}" is a text value, so it needs single quotes.',
                            f'"{inner}"', f"'{inner}'",
                            "Standard SQL: single quotes = text values, double quotes = identifiers."))
        return f"'{inner}'"

    new = re.sub(r'"([^"\']*)"', fix, sql)
    return new, issues


def rule_keyword_typos(sql, schema):
    issues, edits = [], []
    known = known_identifiers(schema) | {m.lower() for m in re.findall(r"\bAS\s+(\w+)", mask_strings(sql), re.I)}
    masked = mask_strings(sql)
    for m in re.finditer(r"[A-Za-z_]+", masked):
        word, up = m.group(0), m.group(0).upper()
        before = masked[max(0, m.start() - 1):m.start()]
        if before == "." or word.lower() in known or up in ALL_KEYWORDS:
            continue
        fix = MERGED.get(up) or COMMON_TYPOS.get(up)
        if not fix and len(word) >= 4:
            nxt = masked[m.end():].lstrip()[:1]
            pool = CORE_KEYWORDS + (FUNCTIONS if nxt == "(" else [])
            hit = difflib.get_close_matches(up, pool, n=1, cutoff=0.8)
            fix = hit[0] if hit else None
        if fix:
            edits.append((m.start(), m.end(), fix))
            issues.append(Issue("syntax", "error", f"Misspelled keyword '{word}' -> '{fix}'.", word, fix,
                                "SQL keywords must be spelled exactly; the parser stops at the first unknown word."))
    return apply_edits(sql, edits), issues


def rule_trailing_comma(sql, schema):
    new, n = sub_unquoted(sql, r",(\s*)(?=\b(?:FROM|WHERE|GROUP|ORDER|HAVING|LIMIT)\b|\)|$)", r"\1")
    issues = []
    if n:
        issues.append(Issue("syntax", "error", "Removed a trailing comma before the next clause.",
                            concept="A comma separates items; it cannot be the last thing in a list."))
    return new, issues


def rule_operators(sql, schema):
    issues = []
    for pat, repl, msg, concept in [
        (r"(?:!=|<>)\s*NULL\b", "IS NOT NULL", "'!= NULL' never matches; use IS NOT NULL.",
         "NULL means 'unknown', so comparisons with = or != yield unknown, not true."),
        (r"(?<![<>!=])=\s*NULL\b", "IS NULL", "'= NULL' never matches; use IS NULL.",
         "NULL means 'unknown', so comparisons with = or != yield unknown, not true."),
        (r"(?<![<>!=])==(?!=)", "=", "'==' is not SQL; equality is a single '='.",
         "SQL uses '=' for comparison (not assignment inside WHERE)."),
    ]:
        sql, n = sub_unquoted(sql, pat, repl)
        if n:
            issues.append(Issue("logic" if "NULL" in repl else "syntax", "error", msg, concept=concept))
    return sql, issues


def rule_structure(sql, schema):
    """Clause order, aggregates in WHERE, and missing GROUP BY columns."""
    parts = split_clauses(sql)
    if parts is None:
        return sql, []
    issues, d = [], dict(parts)

    # 1. clause order
    order = [CLAUSE_ORDER.index(k) for k, _ in parts]
    if order != sorted(order):
        parts = sorted(parts, key=lambda p: CLAUSE_ORDER.index(p[0]))
        d = dict(parts)
        issues.append(Issue("syntax", "error", "Clauses were in the wrong order; reordered to "
                            "SELECT, FROM, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT.",
                            concept="SQL clauses must appear in a fixed order."))

    # 2. aggregate inside WHERE -> HAVING
    if "WHERE" in d and AGG_RE.search(mask_strings(d["WHERE"])):
        conds = split_top(d["WHERE"], r"\bAND\b")
        agg = [c for c in conds if AGG_RE.search(mask_strings(c))]
        plain = [c for c in conds if c not in agg]
        d = {k: v for k, v in parts}
        having = " AND ".join(agg + ([d["HAVING"]] if "HAVING" in d else []))
        d["HAVING"] = having
        if plain:
            d["WHERE"] = " AND ".join(plain)
        else:
            d.pop("WHERE")
        issues.append(Issue("logic", "error", "Aggregate function used in WHERE; moved the condition to HAVING.",
                            " AND ".join(agg), "HAVING " + " AND ".join(agg),
                            "WHERE filters rows before grouping; HAVING filters groups after aggregation."))

    # 3. non-aggregated columns must be in GROUP BY
    sel = re.sub(r"^\s*DISTINCT\s+", "", d["SELECT"], flags=re.I)
    items = split_top(sel, ",")
    has_agg = any(AGG_RE.search(i) for i in items)
    if has_agg:
        needed = []
        for it in items:
            if AGG_RE.search(it) or it == "*" or re.fullmatch(r"[\d.]+|'.*'", it):
                continue
            expr = re.sub(r"\s+AS\s+\w+$", "", it, flags=re.I)
            m = re.fullmatch(r"([\w.]+)\s+\w+", expr)
            needed.append(m.group(1) if m else expr)
        have = split_top(d.get("GROUP BY", ""), ",") if d.get("GROUP BY") else []
        missing = [n for n in needed if n.lower() not in {h.lower() for h in have}
                   and n.split(".")[-1].lower() not in {h.split(".")[-1].lower() for h in have}]
        if missing:
            d["GROUP BY"] = ", ".join(have + missing)
            issues.append(Issue("logic", "error", "Non-aggregated column(s) in SELECT were missing from GROUP BY: "
                                + ", ".join(missing) + ".", "", "GROUP BY " + d["GROUP BY"],
                                "When you aggregate, every other selected column must be listed in GROUP BY."))

    if issues:
        parts = sorted(d.items(), key=lambda p: CLAUSE_ORDER.index(p[0]))
        sql = join_clauses(parts)
    return sql, issues


def rule_join_on(sql, schema):
    """JOIN without ON/USING -> add the condition from a foreign key."""
    issues, masked = [], mask_strings(sql)
    seen, edits = [], []
    for m in FROM_RE.finditer(masked):
        kind, table, alias = m.group(1).upper(), m.group(2), m.group(3)
        ref = alias or table
        if kind == "JOIN" and schema.table_name(table):
            tail = masked[m.end():].lstrip()
            if not re.match(r"(ON|USING)\b", tail, re.I) and not re.search(r"\bCROSS\s+JOIN\s*$", masked[:m.start() + 4], re.I):
                for prev_table, prev_ref in reversed(seen):
                    cond = schema.join_condition(prev_table, table)
                    if cond:
                        a, b = cond
                        text = f" ON {prev_ref}.{a} = {ref}.{b}"
                        edits.append((m.end(), m.end(), text))
                        issues.append(Issue("join", "error", f"JOIN {table} had no ON condition; added the foreign-key link"
                                            f" {prev_ref}.{a} = {ref}.{b}.", "", text.strip(),
                                            "A JOIN without ON produces a cartesian product (every row paired with every row)."))
                        break
                else:
                    issues.append(Issue("join", "warning", f"JOIN {table} has no ON condition and no foreign key was found to infer one.",
                                        concept="Specify how the tables relate: JOIN t2 ON t1.key = t2.key."))
        seen.append((table, ref))
    return apply_edits(sql, edits), issues


def rule_style(sql, schema):
    issues = []
    if re.search(r"\bSELECT\s+(?:DISTINCT\s+)?\*", mask_strings(sql), re.I):
        issues.append(Issue("style", "info", "SELECT * returns every column; list only the columns you need.",
                            concept="Naming columns is faster, clearer and safer when the table changes."))
    parts = split_clauses(sql)
    if parts and "FROM" in dict(parts) and "," in dict(parts)["FROM"] and "WHERE" not in dict(parts):
        issues.append(Issue("join", "warning", "Comma-separated tables with no WHERE condition create a cartesian product.",
                            concept="Prefer explicit JOIN ... ON syntax."))
    return sql, issues


SYNTAX_RULES = [rule_balance, rule_double_quotes, rule_keyword_typos, rule_trailing_comma, rule_operators]
LOGIC_RULES = [rule_structure, rule_join_on, rule_style]   # run after table/column names are repaired


# ------------------------------------------------- engine-error repair
def repair_from_error(sql: str, error: str, schema):
    """Use the database error message to fix names. Returns (new_sql, [Issue]) or (None, [])."""
    m = re.match(r"no such table: (\S+)", error)
    if m:
        bad = m.group(1)
        best = closest(bad, schema.table_names())
        if best:
            new, _ = sub_unquoted(sql, rf"\b{re.escape(bad)}\b", best)
            return new, [Issue("table", "error", f"Table '{bad}' does not exist; did you mean '{best}'?", bad, best,
                               "Table names must match the schema exactly.")]
        return None, []

    m = re.match(r"no such column: (\S+)", error)
    if m:
        bad = m.group(1)
        amap = alias_map(sql, schema)
        if "." in bad:
            qual, col = bad.split(".", 1)
            table = amap.get(qual.lower())
            best = closest(col, schema.columns(table)) if table else None
            if best:
                new, _ = sub_unquoted(sql, rf"\b{re.escape(qual)}\s*\.\s*{re.escape(col)}\b", f"{qual}.{best}")
                return new, [Issue("column", "error", f"Column '{bad}' does not exist in {table}; did you mean '{qual}.{best}'?",
                                   bad, f"{qual}.{best}", "Each column belongs to one table; check the schema.")]
            return None, []
        used = sorted({t for t in amap.values()}) or schema.table_names()
        pool = sorted({c for t in used for c in schema.columns(t)})
        best = closest(bad, pool)
        if best:
            new, _ = sub_unquoted(sql, rf"(?<![\w.]){re.escape(bad)}\b", best)
            return new, [Issue("column", "error", f"Column '{bad}' does not exist; did you mean '{best}'?", bad, best,
                               "Column names must match the schema exactly.")]
        owners = [t for t in schema.table_names() if bad.lower() in [c.lower() for c in schema.columns(t)]]
        if owners:
            return None, [Issue("column", "error", f"Column '{bad}' lives in {', '.join(owners)}, which is not in FROM/JOIN.",
                                concept="Join the table that owns the column before using it.")]
        return None, []

    m = re.match(r"ambiguous column name: (\S+)", error)
    if m:
        col = m.group(1)
        for table, alias in parse_from(sql):
            if col.lower() in [c.lower() for c in schema.columns(table)]:
                ref = alias or table
                new, _ = sub_unquoted(sql, rf"(?<![\w.]){re.escape(col)}\b", f"{ref}.{col}")
                return new, [Issue("column", "error", f"Column '{col}' exists in several joined tables; qualified it as {ref}.{col}.",
                                   col, f"{ref}.{col}",
                                   "When two tables share a column name, prefix it with the table or alias. "
                                   "Check that the chosen table is the one you meant.")]
        return None, []
    return None, []
