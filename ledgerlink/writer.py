"""The writer: append one row to a JSON Lines ledger, the one place rows are written.

    ledgerlink.append("deploys", {"svc": "api"}, actor="ci", refs=["task:7"])

The row is copied and every caller field is kept, same values and order. `at` and `actor` are
added only when the row has none. `refs` are merged with the row's own, deduplicated and checked.
The line is written with ONE `os.write` on an O_APPEND descriptor, so concurrent appenders never
interleave a line.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from . import reader
from . import refs as _refs

__all__ = ["LedgerRefused", "append"]

_PLAIN_KEY = re.compile(r"\S+")


class LedgerRefused(ValueError):  # noqa: N818
    """A row the writer refuses: a bad ref, or `configure(validate=...)` said no."""


def _check_ref(ref: Any) -> str:
    if not isinstance(ref, str) or ":" not in ref:
        raise LedgerRefused(f"bad ref (want <store>:<key>): {ref!r}")
    store, key = ref.split(":", 1)
    if store in _refs.stores():
        try:
            _refs.parse(ref)
        except ValueError as exc:
            raise LedgerRefused(str(exc)) from exc
    elif not _refs._NAME.fullmatch(store) or not _PLAIN_KEY.fullmatch(key):
        raise LedgerRefused(f"bad ref (want <store>:<key>): {ref!r}")
    return ref


def _merge_refs(row_refs: Any, extra: Optional[Sequence[str]]) -> List[str]:
    if row_refs is None:
        first: List[Any] = []
    elif isinstance(row_refs, str):
        first = [row_refs]
    elif isinstance(row_refs, (list, tuple)):
        first = list(row_refs)
    else:
        raise LedgerRefused(f"refs must be a list of refs: {row_refs!r}")
    if isinstance(extra, str):
        extra = [extra]
    merged: List[str] = []
    for ref in first + list(extra or ()):
        _check_ref(ref)
        if ref not in merged:
            merged.append(ref)
    return merged


def _actor(actor: Optional[str]) -> str:
    if actor:
        return actor
    env = os.environ.get(reader._config["actor_env"] or reader.ACTOR_ENV)
    if env:
        return env
    stem = os.path.splitext(os.path.basename(sys.argv[0] if sys.argv else ""))[0]
    return f"script:{stem or 'python'}"


def _clean(value: Any, fn: Any) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {_clean(k, fn): _clean(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v, fn) for v in value]
    return value


def append(
    name: str,
    row: Dict[str, Any],
    *,
    actor: Optional[str] = None,
    refs: Optional[Sequence[str]] = None,
    root: Optional[str] = None,
    path: Optional[str] = None,
    ensure_ascii: bool = False,
) -> Dict[str, Any]:
    """Append `row` to ledger `name` and return the dict written."""
    out: Dict[str, Any] = dict(row)
    if "at" not in out:
        out["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if "actor" not in out:
        out["actor"] = _actor(actor)
    merged = _merge_refs(out.get("refs"), refs)
    if merged:
        out["refs"] = merged
    clean = reader._config["clean"]
    if clean is not None:
        out = _clean(out, clean)
    validate = reader._config["validate"]
    if validate is not None:
        validate(out)
    if path is None:
        adapter = reader._config["adapters"].get(name, reader.DEFAULT_ADAPTER)
        path = reader.ledger_path(name, adapter, root)
    data = (json.dumps(out, ensure_ascii=ensure_ascii, default=str) + "\n").encode("utf-8")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return out
