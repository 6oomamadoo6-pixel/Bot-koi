"""Small psycopg2-compatible adapter for the Golden Chat Turso migration.

The bot uses PostgreSQL-style placeholders and a few PostgreSQL SQL extensions.
This module keeps the existing call sites stable while translating the supported
subset to SQLite/libSQL. It is intentionally isolated so the migration can be
reviewed and rolled back without touching the original main branch.
"""
import os
import re
import queue
import threading
from datetime import datetime
from types import SimpleNamespace

import turso_serverless


TRANSACTION_STATUS_IDLE = 0
TRANSACTION_STATUS_INTRANS = 2


def _to_db_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, bool):
        return int(value)
    return value


def _from_db_value(value):
    if not isinstance(value, str):
        return value
    # Convert only canonical SQLite timestamp strings, leaving arbitrary text intact.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?", value):
        try:
            return datetime.fromisoformat(value.replace(" ", "T", 1))
        except ValueError:
            return value
    return value


class OperationalError(Exception):
    pass


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.raw = connection.raw.cursor()
        self._skip = False

    def execute(self, sql, params=None):
        params = tuple(params or ())
        sql = str(sql)

        # PostgreSQL's ADD COLUMN IF NOT EXISTS is not supported by SQLite.
        alter = re.match(
            r"^\s*ALTER\s+TABLE\s+([A-Za-z_][\w]*)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+([A-Za-z_][\w]*)\s+([\s\S]+?)\s*;?\s*$",
            sql, re.IGNORECASE
        )
        if alter:
            table, column, definition = alter.groups()
            info = self.connection.raw.execute("PRAGMA table_info(" + table + ")").fetchall()
            names = {str(row[1]).lower() for row in info}
            if column.lower() in names:
                self._skip = True
                return self
            sql = "ALTER TABLE " + table + " ADD COLUMN " + column + " " + definition

        # PostgreSQL-specific upsert metadata: determine insert/update before the write.
        if re.search(r"\(\s*xmax\s*=\s*0\s*\)\s+AS\s+is_new", sql, re.IGNORECASE):
            existed = False
            if params:
                try:
                    found = self.connection.raw.execute(
                        "SELECT 1 FROM users WHERE user_id = ?", (_to_db_value(params[0]),)
                    ).fetchone()
                    existed = found is not None
                except Exception:
                    existed = False
            sql = re.sub(
                r",\s*\(\s*xmax\s*=\s*0\s*\)\s+AS\s+is_new",
                ", " + ("0" if existed else "1") + " AS is_new",
                sql, flags=re.IGNORECASE
            )

        sql = re.sub(r"\bBIGSERIAL\s+PRIMARY\s+KEY\b",
                     "INTEGER PRIMARY KEY AUTOINCREMENT", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\bILIKE\b", "LIKE", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\s+FOR\s+UPDATE\b", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"::\s*text\b", "", sql, flags=re.IGNORECASE)

        # Translate the interval expressions used by the bot and admin panel.
        sql = re.sub(
            r"CURRENT_TIMESTAMP\s*-\s*INTERVAL\s+'(\d+)\s+(hours?|days?|minutes?)'",
            lambda m: "datetime('now', '-" + m.group(1) + " " + m.group(2).rstrip("s") + "')",
            sql, flags=re.IGNORECASE
        )
        sql = re.sub(
            r"CURRENT_TIMESTAMP\s*\+\s*\(%s\s*\*\s*INTERVAL\s+'1\s+day'\)",
            "datetime('now', printf('%+d days', %s))",
            sql, flags=re.IGNORECASE
        )

        sql = sql.replace("%s", "?")
        bound = tuple(_to_db_value(v) for v in params)
        self._skip = False
        self.raw.execute(sql, bound)
        command = re.match(r"^\s*([A-Za-z]+)", sql)
        command = command.group(1).upper() if command else ""
        if command in ("COMMIT", "END", "ROLLBACK"):
            self.connection._transaction_active = False
        else:
            # DB-API drivers may retain a transaction after reads as well as writes.
            # Mark it active; commit/rollback clears the state.
            self.connection._transaction_active = True
        return self

    def fetchone(self):
        if self._skip:
            return None
        row = self.raw.fetchone()
        return tuple(_from_db_value(v) for v in row) if row is not None else None

    def fetchall(self):
        if self._skip:
            return []
        return [tuple(_from_db_value(v) for v in row) for row in self.raw.fetchall()]

    @property
    def rowcount(self):
        return 0 if self._skip else self.raw.rowcount

    @property
    def lastrowid(self):
        return self.raw.lastrowid

    @property
    def description(self):
        return self.raw.description

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class Connection:
    def __init__(self, raw):
        self.raw = raw
        self.closed = False
        self._transaction_active = False

    def cursor(self, *args, **kwargs):
        if self.closed:
            raise OperationalError("Turso connection is closed")
        return Cursor(self)

    def commit(self):
        if not self.closed:
            self.raw.commit()
            self._transaction_active = False

    def rollback(self):
        if not self.closed:
            self.raw.rollback()
            self._transaction_active = False

    def close(self):
        if not self.closed:
            self.raw.close()
            self.closed = True

    def get_transaction_status(self):
        # Match psycopg2's status contract so release_db() rolls back any
        # unfinished DB-API transaction before returning this connection.
        return TRANSACTION_STATUS_INTRANS if self._transaction_active else TRANSACTION_STATUS_IDLE

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def connect(dsn=None, **kwargs):
    url = (dsn or os.getenv("TURSO_DATABASE_URL") or "").strip()
    token = (os.getenv("TURSO_AUTH_TOKEN") or "").strip()
    if not url or not token:
        raise OperationalError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be configured")
    try:
        raw = turso_serverless.connect(url, auth_token=token)
        return Connection(raw)
    except Exception as exc:
        raise OperationalError("Could not connect to Turso: " + str(exc)) from exc


class ThreadedConnectionPool:
    def __init__(self, minconn, maxconn, dsn=None, **kwargs):
        self.dsn = dsn
        self.maxconn = max(1, int(maxconn))
        self._idle = queue.LifoQueue(maxsize=self.maxconn)
        self._lock = threading.Lock()
        self._created = 0
        self._closed = False
        for _ in range(max(0, min(int(minconn), self.maxconn))):
            self._idle.put(connect(self.dsn))
            self._created += 1

    def getconn(self):
        if self._closed:
            raise OperationalError("Turso connection pool is closed")
        try:
            conn = self._idle.get_nowait()
            if conn.closed:
                conn = connect(self.dsn)
            return conn
        except queue.Empty:
            with self._lock:
                if self._created < self.maxconn:
                    self._created += 1
                    return connect(self.dsn)
            # All pool slots are busy; wait for one to be returned.
            conn = self._idle.get()
            return connect(self.dsn) if conn.closed else conn

    def putconn(self, conn, close=False):
        if conn is None:
            return
        if close or self._closed or conn.closed:
            conn.close()
            with self._lock:
                self._created = max(0, self._created - 1)
            return
        try:
            self._idle.put_nowait(conn)
        except queue.Full:
            conn.close()
            with self._lock:
                self._created = max(0, self._created - 1)

    def closeall(self):
        self._closed = True
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                break
        with self._lock:
            self._created = 0


pool = SimpleNamespace(ThreadedConnectionPool=ThreadedConnectionPool)
extensions = SimpleNamespace(TRANSACTION_STATUS_IDLE=TRANSACTION_STATUS_IDLE,
                             TRANSACTION_STATUS_INTRANS=TRANSACTION_STATUS_INTRANS)
psycopg2 = SimpleNamespace(connect=connect, OperationalError=OperationalError,
                            pool=pool, extensions=extensions)
