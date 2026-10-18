"""Schema awareness: loads DDL into an in-memory SQLite DB and introspects it.

The database is used for two things:
  1. Ground truth about tables, columns and foreign keys (for fixing names and joins).
  2. A real SQL engine to validate queries (EXPLAIN) and preview results.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class Schema:
    conn: sqlite3.Connection
    ddl: str = ""
    tables: dict = field(default_factory=dict)   # lower name -> (real name, [columns])
    fks: list = field(default_factory=list)      # (child_table, child_col, parent_table, parent_col)

    @classmethod
    def from_ddl(cls, ddl: str) -> "Schema":
        conn = sqlite3.connect(":memory:")
        conn.executescript(ddl)
        schema = cls(conn=conn, ddl=ddl)
        schema._introspect()
        return schema

    @classmethod
    def from_file(cls, path: str) -> "Schema":
        with open(path, encoding="utf-8") as f:
            return cls.from_ddl(f.read())

    def _introspect(self) -> None:
        names = [r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        pks = {}
        for name in names:
            info = self.conn.execute(f'PRAGMA table_info("{name}")').fetchall()
            self.tables[name.lower()] = (name, [r[1] for r in info])
            pks[name.lower()] = [r[1] for r in info if r[5]]
        for name in names:
            for row in self.conn.execute(f'PRAGMA foreign_key_list("{name}")'):
                parent, child_col, parent_col = row[2], row[3], row[4]
                if parent_col is None:
                    pk = pks.get(parent.lower(), [])
                    parent_col = pk[0] if pk else None
                if parent_col:
                    self.fks.append((name, child_col, parent, parent_col))

    # ---- lookups -------------------------------------------------------
    def table_name(self, name: str):
        entry = self.tables.get(name.lower())
        return entry[0] if entry else None

    def columns(self, table: str) -> list:
        entry = self.tables.get(table.lower())
        return list(entry[1]) if entry else []

    def all_columns(self) -> list:
        return sorted({c for _, cols in self.tables.values() for c in cols})

    def table_names(self) -> list:
        return [real for real, _ in self.tables.values()]

    def join_condition(self, a: str, b: str):
        """Return (a_col, b_col) if a foreign key links table a and b."""
        for child, ccol, parent, pcol in self.fks:
            if child.lower() == a.lower() and parent.lower() == b.lower():
                return ccol, pcol
            if child.lower() == b.lower() and parent.lower() == a.lower():
                return pcol, ccol
        return None

    # ---- engine --------------------------------------------------------
    def validate(self, sql: str):
        """Return None if the engine accepts the query, otherwise the error text."""
        try:
            self.conn.execute("EXPLAIN " + sql)
            return None
        except sqlite3.Error as exc:
            return str(exc)

    def preview(self, sql: str, limit: int = 5):
        """Run a read-only query and return (columns, rows) or None."""
        if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
            return None
        try:
            cur = self.conn.execute(sql)
            cols = [d[0] for d in cur.description]
            return cols, cur.fetchmany(limit)
        except sqlite3.Error:
            return None
