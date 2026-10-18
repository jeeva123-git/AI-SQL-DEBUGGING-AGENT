# AI SQL Debugging Agent

An agent that **detects, analyzes and corrects errors in SQL queries**, then explains each fix in plain
language so users learn the underlying database concept. Built for students, developers and DBAs.

## How it works

```
 broken SQL + schema
        |
 1. Syntax rules      typos (SELCT/FORM), GROUPBY, quotes, trailing commas, ==, = NULL, brackets
        |
 2. Engine feedback   run EXPLAIN on an in-memory SQLite copy of the schema;
        |             fix "no such table/column" and "ambiguous column" using fuzzy matching
        |
 3. Logic rules       JOIN without ON (infer from foreign keys), aggregate in WHERE -> HAVING,
        |             missing GROUP BY columns, clause order, SELECT * / cartesian-product warnings
        |
 4. LLM fallback      (optional) Claude repairs what rules cannot; answer is re-validated by the engine
        |
 5. Explanation       per-issue "what + why", or an LLM-written tutor-style summary
        v
 corrected SQL, issue list, explanation, result preview
```

Design choices
- **Schema-aware**: names are fixed against real tables/columns, joins use real foreign keys.
- **Verified fixes**: every correction is validated by an actual SQL engine, so the agent never
  returns a "fix" that still fails. LLM output is accepted only if it validates.
- **Works offline**: the rule engine needs no API key; the LLM only adds coverage and nicer wording.
- **Honest about limits**: if a query cannot be fixed it says so and shows the engine's error.

## Run it

```bash
# CLI (no dependencies)
python -m sql_debug_agent.cli --schema examples/schema.sql --no-llm \
  -q "SELCT c.name, COUNT(o.id) FORM custmers c JOIN orders o WHERE COUNT(o.id) > 1"

# enable the LLM layer
pip install anthropic && export ANTHROPIC_API_KEY=sk-...
python -m sql_debug_agent.cli --schema examples/schema.sql

# web UI (Windows: just double-click run.bat)
pip install streamlit && streamlit run app.py

# tests
python -m unittest discover -s tests -t .
```

Python API
```python
from sql_debug_agent import DebugAgent, Schema
agent = DebugAgent(Schema.from_file("examples/schema.sql"), use_llm=False)
result = agent.debug("SELECT nme FORM customers")
print(result.fixed, result.valid, [i.message for i in result.issues])
```

## Example

Input: `SELCT c.name, COUNT(o.id) FORM custmers c JOIN orders o WHERE COUNT(o.id) > 1`

Output: `SELECT c.name, COUNT(o.id) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name HAVING COUNT(o.id) > 1;`

## Project layout

| File | Role |
|---|---|
| `sql_debug_agent/schema.py` | loads DDL, introspects tables/columns/foreign keys, validates + previews queries |
| `sql_debug_agent/rules.py` | all detection and repair rules, plus engine-error repair |
| `sql_debug_agent/llm.py` | optional Anthropic API calls (fix + explain) |
| `sql_debug_agent/agent.py` | pipeline orchestration, result object, text report |
| `sql_debug_agent/cli.py`, `app.py` | command line and Streamlit interfaces |
| `tests/test_agent.py` | 19 unit tests covering each error class |

## Limitations and future work
- Targets SQLite dialect and single SELECT statements for the structural rules (UNION/CTEs are validated but not restructured).
- Closing-bracket placement is a best guess (end of query).
- Ideas: MySQL/PostgreSQL dialect support via `sqlglot`, INSERT/UPDATE/DELETE rules, performance hints
  (missing indexes), a benchmark of broken-query datasets (e.g. Spider-based) to report accuracy, user-feedback loop.
