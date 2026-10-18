"""Command line interface.

  python -m sql_debug_agent.cli --schema examples/schema.sql -q "SELCT * FORM custmers"
  python -m sql_debug_agent.cli --schema examples/schema.sql            # interactive
"""
from __future__ import annotations

import argparse
import json
import sys

from .agent import DebugAgent, format_report
from .schema import Schema


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI SQL Debugging Agent")
    ap.add_argument("--schema", required=True, help="path to a .sql file with CREATE TABLE statements")
    ap.add_argument("-q", "--query", help="SQL query to debug")
    ap.add_argument("-f", "--file", help="file containing the SQL query")
    ap.add_argument("--no-llm", action="store_true", help="disable the LLM fallback")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)

    agent = DebugAgent(Schema.from_file(args.schema), use_llm=not args.no_llm)

    def run(sql):
        r = agent.debug(sql)
        print(json.dumps(r.to_dict(), indent=2) if args.json else format_report(r))

    if args.query or args.file:
        run(args.query or open(args.file, encoding="utf-8").read())
        return 0

    print("SQL Debugging Agent. Enter a query (end with ';' or a blank line). Ctrl-D to quit.")
    buf = []
    for line in sys.stdin:
        if line.strip() == "" and buf or line.strip().endswith(";"):
            buf.append(line)
            run("".join(buf))
            buf = []
            print()
        elif line.strip():
            buf.append(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
