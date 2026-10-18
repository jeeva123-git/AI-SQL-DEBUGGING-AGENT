"""Streamlit web UI for the AI SQL Debugging Agent.

Run from the project folder:   streamlit run app.py
"""
import os
import sys

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sql_debug_agent import DebugAgent, Schema  # noqa: E402
from sql_debug_agent import llm  # noqa: E402

with open(os.path.join(HERE, "examples", "schema.sql"), encoding="utf-8") as f:
    DEFAULT_SCHEMA = f.read()

SAMPLES = {
    "Typos + bad table + missing JOIN condition + aggregate in WHERE":
        "SELCT c.name, COUNT(o.id) FORM custmers c JOIN orders o WHERE COUNT(o.id) > 1",
    "Wrong column name": "SELECT nme, city FROM customers",
    "NULL comparison and double quotes": 'SELECT name FROM customers WHERE email = NULL AND city == "Chennai"',
    "Missing GROUP BY": "SELECT city, COUNT(*) FROM customers",
    "Ambiguous column": "SELECT id, total FROM customers c JOIN orders o ON c.id = o.customer_id",
    "Clause order": "SELECT name FROM customers LIMIT 2 ORDER BY name",
}

st.set_page_config(page_title="AI SQL Debugging Agent", page_icon="🛠️", layout="wide")
st.title("🛠️ AI SQL Debugging Agent")
st.caption("Detects, explains and fixes SQL errors: syntax, joins, columns and logic.")

# ---- sidebar
with st.sidebar:
    st.header("Settings")
    llm_ready = llm.available()
    use_llm = st.checkbox("Use LLM fallback (Claude)", value=llm_ready, disabled=not llm_ready)
    if not llm_ready:
        st.info("LLM layer is off. To enable it, install `anthropic` and set `ANTHROPIC_API_KEY`. "
                "The rule-based agent works without it.")
    uploaded = st.file_uploader("Upload your own schema (.sql)", type=["sql"])
    st.markdown("Samples")
    choice = st.selectbox("Load a sample broken query", ["(none)"] + list(SAMPLES))

schema_text = uploaded.read().decode("utf-8") if uploaded else DEFAULT_SCHEMA
default_query = SAMPLES.get(choice, SAMPLES[list(SAMPLES)[0]])

# ---- inputs
left, right = st.columns(2)
with left:
    schema_text = st.text_area("Database schema (CREATE TABLE ...)", schema_text, height=320)
with right:
    query = st.text_area("Your SQL query", default_query, height=320, key=f"q-{choice}")

if st.button("Debug my query", type="primary"):
    try:
        schema = Schema.from_ddl(schema_text)
    except Exception as exc:
        st.error(f"Could not load the schema: {exc}")
        st.stop()

    res = DebugAgent(schema, use_llm=use_llm).debug(query)

    if res.valid:
        st.success("Query is now valid for this schema." if res.issues else "No problems found. The query is valid.")
    else:
        st.error(f"Could not fully fix the query. Engine error: {res.remaining_error}")

    st.subheader("Corrected query")
    st.code(res.fixed, language="sql")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader(f"Issues found ({len(res.issues)})")
        badge = {"error": "🔴", "warning": "🟠", "info": "🔵"}
        for i in res.issues:
            st.markdown(f"{badge.get(i.severity, '')} **{i.category}**: {i.message}")
            if i.concept:
                st.caption(f"Why: {i.concept}")
    with c2:
        st.subheader("Explanation")
        st.write(res.explanation)

    if res.preview:
        cols, rows = res.preview
        st.subheader("Result preview (sample data)")
        st.dataframe([dict(zip(cols, r)) for r in rows], use_container_width=True)
