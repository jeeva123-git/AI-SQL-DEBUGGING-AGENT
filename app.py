"""Query Clinic: a SQL debugging agent with switchable AI roles. Streamlit + Groq API."""
import difflib, html, json, random, re, sqlite3, tempfile, os, time
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import sqlparse
import streamlit as st
from groq import Groq

# ════════════════════════════════════════════════════════════
#  PASTE YOUR GROQ API KEY BETWEEN THE QUOTES BELOW
# ════════════════════════════════════════════════════════════
GROQ_API_KEY = "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"  # starts with gsk_
# ════════════════════════════════════════════════════════════
DEFAULT_MODEL = "openai/gpt-oss-20b"  # any chat model available on your Groq account

st.set_page_config(page_title="Query Clinic", page_icon="🩺", layout="wide")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700;800&family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root{--bg:#0D2B33;--panel:#143A44;--line:#245462;--ink:#E6F1EE;--mute:#8FB3B3;--amber:#FFB020;--mint:#7FE3C3;--rose:#FF6B81}
.stApp{background:radial-gradient(1200px 600px at 80% -10%,#1B4A57 0%,var(--bg) 60%);color:var(--ink);font-family:'DM Sans',sans-serif}
h1,h2,h3,h4{font-family:'Bricolage Grotesque',sans-serif!important;letter-spacing:-.02em}
section[data-testid=stSidebar]{background:#0A2229;border-right:1px solid var(--line)}
.hero h1{font-size:3.2rem;font-weight:800;margin:0;line-height:1.05}
.hero p{color:var(--mute);max-width:58ch;margin:.5rem 0 0;font-size:1.05rem}
.pipe{display:flex;align-items:center;flex-wrap:wrap;margin:18px 0 22px}
.stage{display:flex;align-items:center;gap:10px;padding:10px 18px;border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--mute);font-weight:600}
.stage i{width:10px;height:10px;border-radius:50%;background:var(--line)}
.stage.active{color:var(--ink);border-color:var(--amber)}
.stage.active i{background:var(--amber);animation:pulse 1.1s infinite}
.stage.done{color:var(--ink);border-color:var(--mint)}
.stage.done i{background:var(--mint)}
.stage.failed{color:var(--ink);border-color:var(--rose)}
.stage.failed i{background:var(--rose)}
.link{flex:0 0 32px;height:2px;background:var(--line)}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(255,176,32,.7)}100%{box-shadow:0 0 0 12px rgba(255,176,32,0)}}
@media (prefers-reduced-motion:reduce){.stage.active i{animation:none}}
.rail{border-left:2px solid var(--line);margin:6px 0 0 8px;padding-left:24px}
.node{position:relative;padding:0 0 18px}
.node .dot{position:absolute;left:-33px;top:4px;width:14px;height:14px;border-radius:50%;background:var(--line);border:2px solid var(--bg)}
.node.ok .dot{background:var(--mint)}.node.err .dot{background:var(--rose)}.node.run .dot{background:var(--amber)}
.node .ttl{font-weight:600;display:flex;gap:10px;align-items:baseline}
.node .ms{color:var(--mute);font-size:.8rem;font-weight:400}
.node .det{color:var(--mute);font-size:.85rem;font-family:'JetBrains Mono',monospace;margin-top:2px}
.diff{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.diff pre{margin:0;padding:14px 0;border:1px solid var(--line);border-radius:10px;background:#0A2229;font:13px/1.7 'JetBrains Mono',monospace;overflow-x:auto}
.diff pre span{display:block;padding:0 14px;white-space:pre}
.diff b{display:block;margin-bottom:8px}
.diff .ln-del{background:rgba(255,107,129,.18)}
.diff .ln-add{background:rgba(127,227,195,.18)}
.issue{border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:12px 16px;margin-bottom:10px;background:var(--panel)}
.issue.critical{border-left-color:var(--rose)}.issue.warning{border-left-color:var(--amber)}.issue.info{border-left-color:var(--mint)}
.issue h4{margin:0 0 4px;font-size:1.05rem}
.issue p{margin:0;color:var(--mute)}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ───────────────────────── Sandbox database ─────────────────────────
def build_sample_db():
    rnd = random.Random(7)
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.executescript("""
    CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, email TEXT, country TEXT, signup_date TEXT);
    CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
    CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id), order_date TEXT, status TEXT, total REAL);
    CREATE TABLE order_items(id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), product_id INTEGER REFERENCES products(id), quantity INTEGER);
    """)
    names = ["Asha", "Ben", "Chen", "Dara", "Eli", "Farah", "Gus", "Hana", "Ivan", "Jia",
             "Kofi", "Lena", "Mo", "Nia", "Omar", "Pia", "Quin", "Raj", "Sana", "Tom"]
    for i, n in enumerate(names, 1):
        c.execute("INSERT INTO customers VALUES(?,?,?,?,?)", (i, n, f"{n.lower()}@example.com",
                  rnd.choice(["India", "USA", "Germany", "Brazil", "Japan"]),
                  str(date(2024, 1, 1) + timedelta(days=rnd.randint(0, 500)))))
    cats = {"Books": (8, 35), "Gear": (20, 150), "Home": (12, 90), "Toys": (6, 45)}
    prices = {}
    for i in range(1, 17):
        cat = list(cats)[i % 4]
        prices[i] = round(rnd.uniform(*cats[cat]), 2)
        c.execute("INSERT INTO products VALUES(?,?,?,?)", (i, f"{cat} item {i}", cat, prices[i]))
    item_id = 1
    for oid in range(1, 91):  # customers 18-20 never order, on purpose
        total = 0
        for _ in range(rnd.randint(1, 3)):
            pid, qty = rnd.randint(1, 16), rnd.randint(1, 4)
            c.execute("INSERT INTO order_items VALUES(?,?,?,?)", (item_id, oid, pid, qty))
            total += prices[pid] * qty
            item_id += 1
        c.execute("INSERT INTO orders VALUES(?,?,?,?,?)", (oid, rnd.randint(1, 17),
                  str(date(2025, 1, 1) + timedelta(days=rnd.randint(0, 400))),
                  rnd.choice(["shipped", "shipped", "pending", "cancelled"]), round(total, 2)))
    c.commit()
    return c

def get_connection(uploaded):
    if uploaded is None:
        return build_sample_db()
    path = os.path.join(tempfile.gettempdir(), f"qc_{abs(hash(uploaded.name))}.db")
    with open(path, "wb") as f:
        f.write(uploaded.getvalue())
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)

def read_schema(conn):
    out = {}
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        out[t] = {"cols": [(r[1], r[2], r[5]) for r in conn.execute(f'PRAGMA table_info("{t}")')],
                  "fks": [(r[3], r[2], r[4]) for r in conn.execute(f'PRAGMA foreign_key_list("{t}")')]}
    return out

def schema_text(schema):
    lines = []
    for t, m in schema.items():
        cols = ", ".join(f"{c} {ty}{' PK' if pk else ''}" for c, ty, pk in m["cols"])
        fks = "".join(f" | FK {t}.{f} -> {to}.{col}" for f, to, col in m["fks"])
        lines.append(f"{t}({cols}){fks}")
    return "\n".join(lines)

ALLOWED = {21, 20, 31, getattr(sqlite3, "SQLITE_RECURSIVE", 33)}  # SELECT, READ, FUNCTION, RECURSIVE
def _read_only(action, *_):
    return sqlite3.SQLITE_OK if action in ALLOWED else sqlite3.SQLITE_DENY

def run_sql(conn, sql, limit=500):
    t0 = time.perf_counter()
    clean = sql.strip().rstrip(";")
    conn.set_authorizer(_read_only)  # sandbox can only read
    try:
        cur = conn.execute(clean)
        rows = cur.fetchmany(limit)
        cols = [d[0] for d in cur.description] if cur.description else []
        plan = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + clean)]
        return {"ok": True, "df": pd.DataFrame(rows, columns=cols), "plan": plan,
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round((time.perf_counter() - t0) * 1000, 1)}
    finally:
        conn.set_authorizer(None)

# ───────────────────────── Groq ─────────────────────────
SYSTEM = """You are Query Clinic, an expert SQL debugging agent. Find every bug in the user's query: syntax errors, wrong names, bad joins, aggregate misuse, NULL traps, filters that silently break outer joins, and logic that contradicts the stated intent.
Reply with ONLY a JSON object, no markdown:
{"diagnosis": str (one sentence), "issues": [{"title": str, "severity": "critical"|"warning"|"info", "explanation": str}],
 "fixed_sql": str, "explanation": str, "confidence": int 0-100, "tips": [str]}
Rules: use only tables and columns in the schema. Preserve the user's intent. fixed_sql is one read-only statement in the requested dialect, formatted over several lines."""

def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(re.search(r"\{.*\}", text, re.S).group(0))

ASSISTANT_PROMPT = """You are an expert SQL assistant inside an app called Query Clinic.
- When the user asks for SQL, give the query first in a ```sql block, written for the requested dialect.
- After the code, explain it briefly: two to five short sentences or bullets, no long essays.
- For concept questions (joins, indexes, window functions, normalisation and so on), give a short plain-language answer and one tiny example.
- If a request is ambiguous, state your assumption in one line and answer anyway.
- If the question is not about SQL or databases, say so politely in one sentence."""

STARTERS = ["Write a query for the top 5 customers by total spend",
            "Explain INNER JOIN vs LEFT JOIN with an example",
            "What is a window function? Show ROW_NUMBER",
            "How do indexes speed up a query?"]

def current_key():
    return GROQ_API_KEY.strip()

def ask(client, model, messages):
    """JSON reply for the agent loop. Retries without JSON mode if the model rejects it."""
    for use_json in (True, False):
        try:
            kw = {"response_format": {"type": "json_object"}} if use_json else {}
            r = client.chat.completions.create(model=model, messages=messages, temperature=0.1, **kw)
            text = r.choices[0].message.content or ""
            if text.strip():
                return text, parse_json(text)
        except Exception:
            if not use_json:
                raise
    raise RuntimeError("The model returned an empty or invalid reply. Try again or choose another model.")

def stream_reply(client, model, messages):
    for chunk in client.chat.completions.create(model=model, messages=messages, temperature=0.4, stream=True):
        if chunk.choices:
            yield chunk.choices[0].delta.content or ""

# ───────────────────────── Agent loop ─────────────────────────
STAGES = ["Inspect", "Diagnose", "Verify"]

def pipe_html(states):
    parts = []
    for i, (name, s) in enumerate(zip(STAGES, states)):
        parts += ['<div class="link"></div>'] if i else []
        parts.append(f'<div class="stage {s}"><i></i>{name}</div>')
    return f'<div class="pipe">{"".join(parts)}</div>'

def trace_html(trace):
    nodes = "".join(
        f'<div class="node {n["status"]}"><div class="dot"></div><div class="ttl">{html.escape(n["title"])}'
        f'<span class="ms">{n["ms"]} ms</span></div>'
        f'<div class="det">{html.escape(n["detail"]).replace(chr(10), "<br>")}</div></div>' for n in trace)
    return f'<div class="rail">{nodes}</div>'

def run_agent(client, model, conn, sql, err_in, intent, dialect, sandbox, max_tries, pipe_ph, trace_ph):
    states, trace = ["pending"] * 3, []

    def paint():
        pipe_ph.markdown(pipe_html(states), unsafe_allow_html=True)
        trace_ph.markdown(trace_html(trace), unsafe_allow_html=True)

    def add(title):
        n = {"title": title, "detail": "", "status": "run", "ms": 0}
        trace.append(n); paint()
        return n

    def finish(n, status, detail, t0):
        n.update(status=status, detail=detail, ms=round((time.perf_counter() - t0) * 1000))
        paint()

    # 1 Inspect
    states[0] = "active"; t0 = time.perf_counter()
    n = add("Reading the schema and running your query")
    schema = read_schema(conn)
    orig = run_sql(conn, sql) if sandbox else None
    if orig is None:
        orig_txt, status = "Sandbox is off", "ok"
    elif orig["ok"]:
        orig_txt, status = f"Ran without errors and returned {len(orig['df'])} rows", "ok"
    else:
        orig_txt, status = orig["error"], "err"
    finish(n, status, orig_txt, t0); states[0] = "done"

    # 2 Diagnose, 3 Verify (retry loop)
    prompt = (f"Dialect: {dialect}\n\nSchema:\n{schema_text(schema)}\n\nQuery:\n{sql}\n\n"
              f"Error reported by user: {err_in or 'none'}\nSandbox result: {orig_txt}\n"
              f"Intended behaviour: {intent or 'not stated'}")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    data, ver, tries = {}, None, 0
    while tries < max_tries:
        tries += 1
        states[1] = "active"; t0 = time.perf_counter()
        n = add(f"Asking Groq for a diagnosis (attempt {tries})")
        text, data = ask(client, model, messages)
        finish(n, "ok", data.get("diagnosis", ""), t0); states[1] = "done"
        messages.append({"role": "assistant", "content": text})
        states[2] = "active"; t0 = time.perf_counter()
        if not sandbox:
            n = add("Sandbox verification skipped"); finish(n, "ok", "Turn the sandbox on to test the fix.", t0)
            states[2] = "done"; break
        n = add("Testing the fix in the read-only sandbox")
        ver = run_sql(conn, data.get("fixed_sql", ""))
        if ver["ok"]:
            finish(n, "ok", f"{len(ver['df'])} rows in {ver['ms']} ms", t0); states[2] = "done"; break
        finish(n, "err", ver["error"], t0); states[2] = "failed"
        messages.append({"role": "user", "content":
                         f"Your fixed_sql failed in the sandbox: {ver['error']}\nReturn corrected JSON in the same format."})
    return {"sql": sql, "data": data, "orig": orig, "ver": ver, "trace": trace, "schema": schema,
            "states": states, "tries": tries, "sandbox": sandbox}

# ───────────────────────── Result views ─────────────────────────
def pretty(sql):
    return sqlparse.format(sql, reindent=True, keyword_case="upper").strip()

def side_by_side(a, b):
    A, B = a.splitlines(), b.splitlines()
    left, right = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, A, B).get_opcodes():
        cls = "" if tag == "equal" else None
        left += [f'<span class="{cls if cls is not None else "ln-del"}">{html.escape(x) or "&nbsp;"}</span>' for x in A[i1:i2]]
        right += [f'<span class="{cls if cls is not None else "ln-add"}">{html.escape(x) or "&nbsp;"}</span>' for x in B[j1:j2]]
    return (f'<div class="diff"><div><b>Before</b><pre>{"".join(left)}</pre></div>'
            f'<div><b>After</b><pre>{"".join(right)}</pre></div></div>')

def schema_dot(schema):
    g = ['digraph{rankdir=LR;bgcolor="transparent";node[shape=plaintext,fontname="Helvetica",fontcolor="#E6F1EE"];'
         'edge[color="#7FE3C3"];']
    for t, m in schema.items():
        rows = "".join(f'<TR><TD ALIGN="LEFT" PORT="{c}">{c}{"  (PK)" if pk else ""}</TD>'
                       f'<TD ALIGN="LEFT"><FONT COLOR="#8FB3B3">{ty}</FONT></TD></TR>' for c, ty, pk in m["cols"])
        g.append(f'{t}[label=<<TABLE BORDER="1" COLOR="#245462" CELLBORDER="0" CELLSPACING="0" CELLPADDING="5" '
                 f'BGCOLOR="#143A44"><TR><TD COLSPAN="2" BGCOLOR="#245462"><B>{t}</B></TD></TR>{rows}</TABLE>>];')
    for t, m in schema.items():
        for frm, to, col in m["fks"]:
            g.append(f'{t}:{frm} -> {to}{":" + col if col else ""};')
    return "".join(g) + "}"

def gauge(value):
    fig = go.Figure(go.Indicator(mode="gauge+number", value=value, number={"suffix": "%"},
        title={"text": "Fix confidence"},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#7FE3C3"}, "bgcolor": "#143A44", "bordercolor": "#245462"}))
    fig.update_layout(height=240, margin=dict(t=50, b=10, l=30, r=30), paper_bgcolor="rgba(0,0,0,0)", font_color="#E6F1EE")
    return fig

def show_result(res):
    d, ver, orig = res["data"], res["ver"], res["orig"]
    fixed = d.get("fixed_sql", "")
    tabs = st.tabs(["Fix", "Diagnosis", "Result", "Query plan", "Agent trace", "Schema"])

    with tabs[0]:
        if ver and ver["ok"]:
            st.success(f"Fix verified in the sandbox: {len(ver['df'])} rows in {ver['ms']} ms.")
        elif not res["sandbox"]:
            st.info("The fix was not executed because the sandbox is off.")
        else:
            st.error(f"The fix still fails after {res['tries']} attempts. Review it carefully before use.")
        st.markdown(side_by_side(pretty(res["sql"]), pretty(fixed)), unsafe_allow_html=True)
        st.markdown("#### Fixed query")
        st.code(pretty(fixed), language="sql")
        st.download_button("Download fixed.sql", pretty(fixed), "fixed.sql")
        st.markdown("#### What changed")
        st.write(d.get("explanation", ""))

    with tabs[1]:
        c1, c2 = st.columns([1, 2])
        c1.plotly_chart(gauge(int(d.get("confidence", 0))), use_container_width=True)
        with c2:
            for i in d.get("issues", []):
                sev = i.get("severity", "info")
                st.markdown(f'<div class="issue {sev}"><h4>{html.escape(i.get("title", ""))}</h4>'
                            f'<p>{html.escape(i.get("explanation", ""))}</p></div>', unsafe_allow_html=True)
        if d.get("tips"):
            st.markdown("#### Tips")
            for t in d["tips"]:
                st.markdown(f"- {t}")

    with tabs[2]:
        if ver and ver["ok"]:
            df = ver["df"]
            m1, m2, m3 = st.columns(3)
            m1.metric("Rows (fixed)", len(df))
            m2.metric("Run time", f"{ver['ms']} ms")
            if orig and orig["ok"]:
                m3.metric("Rows (original)", len(orig["df"]), delta=len(df) - len(orig["df"]))
            st.dataframe(df, use_container_width=True)
            num = df.select_dtypes("number").columns
            cat = [c for c in df.columns if c not in num]
            if len(num) and cat and 2 <= len(df) <= 60:
                fig = go.Figure(go.Bar(x=df[cat[0]], y=df[num[0]], marker_color="#7FE3C3"))
                fig.update_layout(title=f"{num[0]} by {cat[0]}", paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)", font_color="#E6F1EE", height=340)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Run the fix in the sandbox to preview results.")

    with tabs[3]:
        if ver and ver["ok"]:
            st.code("\n".join(ver["plan"]) or "No plan returned", language="text")
            if any("SCAN" in p and "USING" not in p for p in ver["plan"]):
                st.warning("A full table scan appears in the plan. An index on the filtered or joined column may help.")
        else:
            st.info("No plan available.")

    with tabs[4]:
        st.markdown(trace_html(res["trace"]), unsafe_allow_html=True)

    with tabs[5]:
        st.graphviz_chart(schema_dot(res["schema"]), use_container_width=True)

# ───────────────────────── Page ─────────────────────────
EXAMPLES = {
    "Aggregate used in WHERE": (
        "select c.name, count(o.id) as orders, sum(o.total) as spent from customers c "
        "join orders o on o.customer_id = c.id where sum(o.total) > 200 group by c.name order by spent desc",
        "misuse of aggregate function SUM()", "Customers whose total spend is above 200"),
    "Typo in a column name": (
        "SELECT name, price FROM products WHERE category = 'Books' ORDER BY pricee DESC", "",
        "Books sorted by price, highest first"),
    "Silent logic bug (no error)": (
        "SELECT c.name, COALESCE(SUM(oi.quantity * p.price), 0) AS revenue FROM customers c "
        "LEFT JOIN orders o ON o.customer_id = c.id JOIN order_items oi ON oi.order_id = o.id "
        "JOIN products p ON p.id = oi.product_id WHERE o.status = 'shipped' GROUP BY c.name", "",
        "Shipped revenue for every customer, with 0 for customers who have no shipped orders"),
}

def load_example():
    st.session_state.sql, st.session_state.err, st.session_state.intent = EXAMPLES[st.session_state.example]

if "sql" not in st.session_state:
    st.session_state.example = list(EXAMPLES)[0]
    load_example()

with st.sidebar:
    st.markdown("### Mode")
    mode = st.radio("Mode", ["SQL Debugger", "Ask for SQL code"], label_visibility="collapsed")
    st.markdown("### Settings")
    model = st.text_input("Groq model", DEFAULT_MODEL)
    dialect = st.selectbox("SQL dialect", ["SQLite", "PostgreSQL", "MySQL", "SQL Server", "BigQuery", "Oracle"])
    if mode == "SQL Debugger":
        sandbox = st.toggle("Test fixes in sandbox", True,
                            help="Runs read-only SELECTs on SQLite. Other dialects may fail on syntax differences.")
        max_tries = st.slider("Max repair attempts", 1, 4, 3)
        uploaded = st.file_uploader("Use your own SQLite file", type=["db", "sqlite", "sqlite3"])
        st.caption("Without a file, the sandbox uses a sample shop database: customers, products, orders, order_items.")
    elif st.session_state.get("assist_msgs") and st.button("Clear chat", use_container_width=True):
        st.session_state.assist_msgs = []
        st.rerun()

def assistant_page():
    st.markdown('<div class="hero"><h1>Query Clinic</h1><p>Ask for any SQL code or concept. '
                'Answers come with the query first and a short explanation.</p></div>', unsafe_allow_html=True)
    msgs = st.session_state.setdefault("assist_msgs", [])
    starter = st.session_state.pop("starter", None)
    if not msgs and not starter:
        st.markdown("#### Try asking")
        cols = st.columns(2)
        for i, text in enumerate(STARTERS):
            if cols[i % 2].button(text, key=f"starter{i}", use_container_width=True):
                st.session_state.starter = text
                st.rerun()
    for m in msgs:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
    prompt = st.chat_input("Ask for SQL code or anything about SQL") or starter
    if not prompt:
        return
    if current_key().startswith("PASTE_"):
        st.error("Add your Groq API key in app.py (GROQ_API_KEY).")
        return
    msgs.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            system = {"role": "system", "content": f"{ASSISTANT_PROMPT}\nTarget dialect: {dialect}."}
            answer = st.write_stream(stream_reply(Groq(api_key=current_key(), timeout=90), model,
                                                  [system] + msgs[-20:])) or "The model returned an empty reply. Try again."
        except Exception as e:
            answer = f"Request failed: {e}"
            st.error(answer)
    msgs.append({"role": "assistant", "content": answer})

if mode == "Ask for SQL code":
    assistant_page()
    st.stop()

st.markdown('<div class="hero"><h1>Query Clinic</h1>'
            '<p>Paste a broken query. The agent reads your schema, diagnoses the fault with Groq, '
            'tests the fix against a read-only sandbox, and retries until it works.</p></div>', unsafe_allow_html=True)

pipe_ph = st.empty()
pipe_ph.markdown(pipe_html(["pending"] * 3), unsafe_allow_html=True)

st.selectbox("Try an example", list(EXAMPLES), key="example", on_change=load_example)
left, right = st.columns([3, 2])
left.text_area("Your SQL", key="sql", height=230)
right.text_area("Error message (optional)", key="err", height=95)
right.text_area("What should it do? (optional)", key="intent", height=95)
go_btn = st.button("Diagnose and fix", type="primary", use_container_width=True)

trace_ph = st.empty()
if go_btn:
    api_key = current_key()
    if api_key.startswith("PASTE_") or not st.session_state.sql.strip():
        st.error("Add your Groq API key in app.py (GROQ_API_KEY) and enter a SQL query.")
    else:
        try:
            client = Groq(api_key=api_key, timeout=90)
            st.session_state.result = run_agent(
                client, model, get_connection(uploaded), st.session_state.sql, st.session_state.err,
                st.session_state.intent, dialect, sandbox, max_tries, pipe_ph, trace_ph)
        except Exception as e:
            st.error(f"The agent stopped: {e}")
trace_ph.empty()

res = st.session_state.get("result")
if res:
    pipe_ph.markdown(pipe_html(res["states"]), unsafe_allow_html=True)
    show_result(res)
