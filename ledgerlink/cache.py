"""The sqlite cache of the envelope rows, tailed by byte offset.

One database, default $XDG_CACHE_HOME/ledgerlink/ledgerlink.sqlite (else
~/.cache/ledgerlink/ledgerlink.sqlite), overridden by the env var LEDGERLINK_CACHE. It is a
cache: never a ledger, safe to delete. Per ledger it keeps (path, inode, size, offset, sig). A
pass parses only the complete lines past the offset; an inode change, a size under the offset
or a changed adapter signature re-reads from 0.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from typing import Any, Dict, Optional

from . import reader

ENV = "LEDGERLINK_CACHE"
BATCH = 5000

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (name TEXT PRIMARY KEY, path TEXT, inode INTEGER,
  size INTEGER, offset INTEGER, sig TEXT);
CREATE TABLE IF NOT EXISTS rows (name TEXT, n INTEGER, at TEXT, actor TEXT, bet TEXT, line TEXT,
  key TEXT, ident TEXT, op TEXT, outcome TEXT, refs TEXT, why TEXT, raw TEXT,
  PRIMARY KEY (name, n));
CREATE INDEX IF NOT EXISTS rows_key ON rows (name, key);
CREATE INDEX IF NOT EXISTS rows_ident ON rows (name, ident);
CREATE INDEX IF NOT EXISTS rows_at ON rows (name, at);
CREATE INDEX IF NOT EXISTS rows_bet ON rows (name, bet);
CREATE INDEX IF NOT EXISTS rows_line ON rows (name, line);
"""
COLUMNS = ("at", "actor", "bet", "line", "key", "op", "outcome", "refs", "why", "raw")


def default_path() -> str:
    env = os.environ.get(ENV)
    if env:
        return os.path.expanduser(env)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join("~", ".cache")
    return os.path.expanduser(os.path.join(base, "ledgerlink", "ledgerlink.sqlite"))


class Cache:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_path()
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=OFF")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Cache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def refresh(self, name: str, path: str, adapter: Dict[str, Any]) -> Dict[str, Any]:
        """Tail `path` into the cache. Returns {"parsed": rows added, "bytes": bytes read,
        "reset": True when it re-read from 0}."""
        sig = reader.signature(adapter, path)
        stats = {"parsed": 0, "bytes": 0, "reset": False}
        try:
            st = os.stat(path)
        except OSError:
            self.db.execute("DELETE FROM rows WHERE name=?", (name,))
            self.db.execute("DELETE FROM files WHERE name=?", (name,))
            self.db.commit()
            return stats
        row = self.db.execute(
            "SELECT inode, size, offset, sig FROM files WHERE name=?", (name,)
        ).fetchone()
        offset = 0
        n = 0
        if row and row[0] == st.st_ino and row[3] == sig and st.st_size >= row[2]:
            offset = row[2]
            n = self.db.execute(
                "SELECT COALESCE(MAX(n), -1) + 1 FROM rows WHERE name=?", (name,)
            ).fetchone()[0]
        else:
            if row:
                stats["reset"] = True
            self.db.execute("DELETE FROM rows WHERE name=?", (name,))
        if offset >= st.st_size:
            self._files(name, path, st, offset, sig)
            return stats
        with open(path, "rb") as fh:
            fh.seek(offset)
            data = fh.read(st.st_size - offset)
        end = data.rfind(b"\n") + 1  # complete lines only: a half written line waits
        batch: list[Any] = []
        for line in data[:end].splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            env = reader.envelope(obj, adapter)
            batch.append(
                (
                    name,
                    n,
                    env["at"],
                    env["actor"],
                    env["bet"],
                    env["line"],
                    env["key"],
                    reader.ident(obj, adapter),
                    env["op"],
                    env["outcome"],
                    json.dumps(env["refs"]),
                    env["why"],
                    line.decode("utf-8", "replace"),
                )
            )
            n += 1
            if len(batch) >= BATCH:
                self._insert(batch)
                stats["parsed"] += len(batch)
                batch = []
        if batch:
            self._insert(batch)
            stats["parsed"] += len(batch)
        stats["bytes"] = end
        self._files(name, path, st, offset + end, sig)
        return stats

    def _insert(self, batch: list[Any]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)

    def _files(self, name: str, path: str, st: os.stat_result, offset: int, sig: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?)",
            (name, path, st.st_ino, st.st_size, offset, sig),
        )
        self.db.commit()

    def rows(
        self,
        name: str,
        since: Optional[str] = None,
        until: Optional[str] = None,
        limit: Optional[int] = None,
        last: bool = False,
        bet: Optional[str] = None,
        line: Optional[str] = None,
        key: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Envelopes of `name` in file order, optionally within [since, until] on `at`."""
        sql = "SELECT at, actor, bet, line, key, op, outcome, refs, why, raw FROM rows WHERE name=?"
        args = [name]
        if since is not None:
            sql += " AND at >= ?"
            args.append(str(since))
        if until is not None:
            sql += " AND at <= ?"
            args.append(str(until))
        for col, want in (("bet", bet), ("line", line), ("key", key)):
            if want is not None:
                sql += f" AND {col} = ?"
                args.append(str(want))
        sql += " ORDER BY n " + ("DESC" if last else "ASC")
        if limit:
            sql += f" LIMIT {int(limit)}"
        for rec in self.db.execute(sql, args):
            yield reader.from_columns(rec)

    def latest(self, name: str, value: Any, by: str = "key") -> Optional[Dict[str, Any]]:
        """The last envelope of `name` whose key (or ident) equals `value`, or None."""
        if by not in ("key", "id"):
            raise ValueError("by is 'key' or 'id'")
        col = "key" if by == "key" else "ident"
        rec = self.db.execute(
            f"SELECT at, actor, bet, line, key, op, outcome, refs, why, raw FROM rows "
            f"WHERE name=? AND {col}=? ORDER BY n DESC LIMIT 1",
            (name, str(value)),
        ).fetchone()
        return reader.from_columns(rec) if rec else None
