"""The reader: every row of a JSON Lines ledger as ONE envelope, through an injected adapter.

Envelope: {at, actor, bet, line, key, op, outcome, refs, why, raw}.

- `at`: when the row happened, normalized (see below).
- `actor`: the row's actor field if the adapter names one, else "row:<line>" when a line is known.
- `bet`: the project (or bet) the row belongs to.
- `line`: "<bet>/<channel>" when both are known (or the adapter's own `line` field).
- `key`: the row's identity in its ledger (fields joined with ":").
- `op`, `outcome`, `why`: the ledger's own words, copied as text.
- `refs`: a list of ref strings (see ledgerlink.refs) the row points at.
- `raw`: the parsed row, untouched.

An adapter is a dict of field lists, first non empty field wins (dotted names reach into nested
objects), except `key` whose fields are joined with ":" when all are present:

    {"at": [...], "bet": [...], "channel": [...], "line": [...], "key": [...], "op": [...],
     "outcome": [...], "why": [...], "refs": [...], "actor": [...], "id": [...],
     "path": "absolute path (optional)"}

`id` is a second, indexed identifier (a job id) for `lookup(..., by="id")`. A ledger with no
adapter reads with `at` and `raw` only.

The ledger directory is `configure(root=...)`, else the env var LEDGERLINK_ROOT, else ".".
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from .cache import Cache

Envelope = Dict[str, Any]
Adapter = Dict[str, Any]

ENVELOPE_KEYS = ("at", "actor", "bet", "line", "key", "op", "outcome", "refs", "why", "raw")
DEFAULT_ADAPTER: Adapter = {"at": ["at"]}
ROOT_ENV = "LEDGERLINK_ROOT"
# Bump whenever envelope() or its helpers change what a row becomes: the cache re-reads from 0.
ENVELOPE_VERSION = 2

ACTOR_ENV = "LEDGERLINK_ACTOR"

_config: Dict[str, Any] = {
    "adapters": {},
    "root": None,
    "actor_env": None,
    "clean": None,
    "validate": None,
}


def configure(
    adapters: Optional[Dict[str, Adapter]] = None,
    root: Optional[str] = None,
    actor_env: Optional[str] = None,
    clean: Optional[Callable[[str], str]] = None,
    validate: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> None:
    """Install the default adapter table and ledger directory, and the writer's settings:
    `actor_env` (the env var `append` reads the actor from, default LEDGERLINK_ACTOR), `clean`
    (applied to every str of a written row) and `validate` (called on the final row, may raise
    LedgerRefused). A setting left None is not changed."""
    if adapters is not None:
        _config["adapters"] = adapters
    if root is not None:
        _config["root"] = root
    if actor_env is not None:
        _config["actor_env"] = actor_env
    if clean is not None:
        _config["clean"] = clean
    if validate is not None:
        _config["validate"] = validate


def _root(root: Optional[str]) -> str:
    return str(root or _config["root"] or os.environ.get(ROOT_ENV) or ".")


def _table(adapters: Optional[Dict[str, Adapter]]) -> Dict[str, Adapter]:
    table: Dict[str, Adapter] = _config["adapters"] if adapters is None else adapters
    return table


def ledger_path(name: str, adapter: Adapter, root: Optional[str] = None) -> str:
    return str(adapter.get("path") or os.path.join(_root(root), name + ".jsonl"))


def _get(row: Any, dotted: str) -> Any:
    cur = row
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _text(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _first(row: Any, fields: Optional[Sequence[str]]) -> Optional[str]:
    for f in fields or ():
        text = _text(_get(row, f))
        if text is not None:
            return text
    return None


def _fromiso(text: str) -> datetime:
    """datetime.fromisoformat as Python 3.11 reads it. Before 3.11 it refuses a "Z", an offset
    without a colon ("+0200") and a fraction that is not 3 or 6 digits: strptime reads those."""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        if sys.version_info >= (3, 11):
            raise
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(f"not an ISO time: {text!r}")


def _at(row: Any, fields: Optional[Sequence[str]]) -> Optional[str]:
    for f in fields or ():
        value = _get(row, f)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (OverflowError, OSError, ValueError):
                return None
        text = str(value)
        if len(text) > 10 and text[10] == " ":
            text = text[:10] + "T" + text[11:]
        if len(text) > 19 and (text.endswith("Z") or text[-5] in "+-" or text[-6] in "+-"):
            try:  # carries a zone: compare in UTC. A zone-less time is kept as written.
                dt = _fromiso(text)
                if dt.tzinfo is not None:
                    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass
        return text
    return None


def _refs(row: Any, fields: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    for f in fields or ():
        value = _get(row, f)
        if isinstance(value, str) and value:
            out.append(value)
        elif isinstance(value, list):
            out.extend(str(v) for v in value if v)
    return out


def _key(row: Any, fields: Optional[Sequence[str]]) -> Optional[str]:
    if not fields:
        return None
    parts = [_text(_get(row, f)) for f in fields]
    return None if any(p is None for p in parts) else ":".join(p for p in parts if p is not None)


def envelope(row: Dict[str, Any], adapter: Optional[Adapter] = None) -> Envelope:
    """The envelope of one parsed row."""
    ad = adapter or DEFAULT_ADAPTER
    bet = _first(row, ad.get("bet"))
    channel = _first(row, ad.get("channel"))
    line = _first(row, ad.get("line"))
    if line is None and bet and channel:
        line = f"{bet}/{channel}"
    actor = _first(row, ad.get("actor"))
    if actor is None and line:
        actor = f"row:{line}"
    return {
        "at": _at(row, ad.get("at")),
        "actor": actor,
        "bet": bet,
        "line": line,
        "key": _key(row, ad.get("key")),
        "op": _first(row, ad.get("op")),
        "outcome": _first(row, ad.get("outcome")),
        "refs": _refs(row, ad.get("refs")),
        "why": _first(row, ad.get("why")),
        "raw": row,
    }


def ident(row: Dict[str, Any], adapter: Optional[Adapter]) -> Optional[str]:
    return _key(row, (adapter or {}).get("id"))


def from_columns(rec: Tuple[Any, ...]) -> Envelope:
    at, actor, bet, line, key, op, outcome, refs, why, raw = rec
    return {
        "at": at,
        "actor": actor,
        "bet": bet,
        "line": line,
        "key": key,
        "op": op,
        "outcome": outcome,
        "refs": json.loads(refs) if refs else [],
        "why": why,
        "raw": json.loads(raw),
    }


def signature(adapter: Adapter, path: str) -> str:
    blob = json.dumps([ENVELOPE_VERSION, adapter, path], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()


def _stream(path: str, adapter: Adapter) -> Iterator[Envelope]:
    try:
        fh = open(path, "rb")  # noqa: SIM115
    except OSError:
        return
    with fh:
        for line in fh:
            if not line.endswith(b"\n") or not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield envelope(obj, adapter)


def _cache(cache: Optional[Cache]) -> Cache:
    from .cache import Cache

    return Cache() if cache is None else cache


def refresh(
    name: str,
    adapters: Optional[Dict[str, Adapter]] = None,
    root: Optional[str] = None,
    cache: Optional[Cache] = None,
) -> Dict[str, Any]:
    """Tail the ledger into the cache; returns the pass stats ({parsed, bytes, reset})."""
    ad = _table(adapters).get(name, DEFAULT_ADAPTER)
    c = _cache(cache)
    try:
        return c.refresh(name, ledger_path(name, ad, root), ad)
    finally:
        if cache is None:
            c.close()


def read(
    name: str,
    *,
    adapters: Optional[Dict[str, Adapter]] = None,
    root: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: Optional[int] = None,
    cache: Any = None,
    bet: Optional[str] = None,
    line: Optional[str] = None,
    key: Optional[str] = None,
) -> Iterator[Envelope]:
    """Yield the envelopes of ledger `name`, in file order, `at` within [since, until].

    `adapters` is the table (name -> adapter); omitted, the table `configure` installed.
    `cache` is a ledgerlink.cache.Cache, or False to stream the file with no cache, or None for
    the default cache (LEDGERLINK_CACHE). The cache is tailed by offset first, so a warm read
    parses only the bytes appended since the last one. `bet`, `line` and `key` filter on those
    envelope fields (indexed in the cache): what a graph walk needs to find what points at a
    record. `since`/`until` compare `at` as text; a time with a zone is normalized to UTC, a
    zone-less one is kept as written."""
    ad = _table(adapters).get(name, DEFAULT_ADAPTER)
    path = ledger_path(name, ad, root)
    if cache is False:
        count = 0
        for env in _stream(path, ad):
            if since is not None and (env["at"] is None or env["at"] < str(since)):
                continue
            if until is not None and (env["at"] is None or env["at"] > str(until)):
                continue
            if any(
                want is not None and env[f] != want
                for f, want in (("bet", bet), ("line", line), ("key", key))
            ):
                continue
            yield env
            count += 1
            if limit and count >= limit:
                return
        return
    c = _cache(cache)
    try:
        c.refresh(name, path, ad)
        yield from c.rows(name, since=since, until=until, limit=limit, bet=bet, line=line, key=key)
    finally:
        if cache is None:
            c.close()


def lookup(
    name: str,
    value: Any,
    by: str = "key",
    *,
    adapters: Optional[Dict[str, Adapter]] = None,
    root: Optional[str] = None,
    cache: Optional[Cache] = None,
) -> Optional[Envelope]:
    """The latest envelope of `name` whose key (by="key") or id (by="id") is `value`, or None."""
    ad = _table(adapters).get(name, DEFAULT_ADAPTER)
    c = _cache(cache)
    try:
        c.refresh(name, ledger_path(name, ad, root), ad)
        return c.latest(name, value, by)
    finally:
        if cache is None:
            c.close()
