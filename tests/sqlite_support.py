"""An in-memory test database that behaves like the MySQL connection the app expects.

It exists ONLY so the saving logic can be tested without a MySQL server. The real
application uses MySQL (see database/schema.sql). A test checks that the tables
below have the same columns as schema.sql, so the two cannot drift apart.
"""
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.services.database import Database

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "database" / "schema.sql"

DDL = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NULL REFERENCES users (id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NULL,
  category TEXT NOT NULL DEFAULT 'business',
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','generated','archived')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE generated_websites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  version INTEGER NOT NULL DEFAULT 1,
  prompt TEXT NOT NULL,
  config_json TEXT NOT NULL,
  model_name TEXT NULL,
  status TEXT NOT NULL DEFAULT 'success' CHECK (status IN ('success','failed')),
  error_message TEXT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (project_id, version)
);
CREATE TABLE project_settings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL UNIQUE REFERENCES projects (id) ON DELETE CASCADE,
  design_style TEXT NOT NULL DEFAULT 'modern',
  color_scheme TEXT NOT NULL DEFAULT 'blue',
  primary_color TEXT NOT NULL DEFAULT '#2563eb',
  font_heading TEXT NOT NULL DEFAULT 'Space Grotesk',
  font_body TEXT NOT NULL DEFAULT 'DM Sans',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class _Cursor:
    def __init__(self, raw, dictionary):
        self._raw = raw
        self._dictionary = dictionary

    def execute(self, sql, params=()):
        self._raw.execute(sql.replace("%s", "?"), tuple(params))

    @property
    def lastrowid(self):
        return self._raw.lastrowid

    def _shape(self, row):
        if row is None:
            return None
        return dict(row) if self._dictionary else tuple(row)

    def fetchone(self):
        return self._shape(self._raw.fetchone())

    def fetchall(self):
        return [self._shape(row) for row in self._raw.fetchall()]

    def close(self):
        self._raw.close()


class _Connection:
    """One shared connection. close() does nothing, so the data survives between calls."""

    def __init__(self):
        self.raw = sqlite3.connect(":memory:", check_same_thread=False)
        self.raw.row_factory = sqlite3.Row
        self.raw.execute("PRAGMA foreign_keys = ON")
        self.lock = threading.RLock()
        self.closed_calls = 0

    def cursor(self, dictionary=False):
        return _Cursor(self.raw.cursor(), dictionary)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.closed_calls += 1

    # helpers for tests
    def run(self, sql, params=()):
        cursor = self.raw.execute(sql, params)
        self.raw.commit()
        return cursor.fetchall()


class _SerializedDatabase(Database):
    """Lets only one request use the shared test connection at a time."""

    def __init__(self, connect, lock):
        super().__init__(connect)
        self._lock = lock

    @contextmanager
    def connection(self):
        with self._lock:
            with super().connection() as connection:
                yield connection


def sqlite_database(with_schema=True):
    """Return (Database, connection) backed by an in-memory test database."""
    connection = _Connection()
    if with_schema:
        connection.raw.executescript(DDL)
    return _SerializedDatabase(lambda: connection, connection.lock), connection


def mysql_schema_tables():
    """Parse database/schema.sql: {table: {"columns": [...], "lengths": {column: max_length}}}."""
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    tables = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\) ENGINE=InnoDB;", text, re.S):
        columns, lengths = [], {}
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            if not line or line.split()[0].upper() in ("PRIMARY", "UNIQUE", "KEY", "CONSTRAINT"):
                continue
            column = line.split()[0]
            columns.append(column)
            match = re.match(r"\w+\s+(?:VARCHAR|CHAR)\((\d+)\)", line)
            if match:
                lengths[column] = int(match.group(1))
        tables[name] = {"columns": columns, "lengths": lengths}
    return tables
