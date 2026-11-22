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


def _own_refs(row_refs: Any) -> List[Any]:
    if row_refs is None:
        return []
    if isinstance(row_refs, str):
        return [row_refs]
    if isinstance(row_refs, (list, tuple)):
        return list(row_refs)
    raise LedgerRefused(f"refs must be a list of refs: {row_refs!r}")


def _apply_refs(out: Dict[str, Any], extra: Optional[Sequence[str]]) -> None:
    """Check every ref of the row and of `extra`. The row's own `refs` value is left as it is
    unless `extra` adds refs: then the merged, deduplicated list is written."""
    own = _own_refs(out.get("refs"))
    added = [extra] if isinstance(extra, str) else list(extra or ())
    for ref in own + added:
        _check_ref(ref)
    if added:
        out["refs"] = list(dict.fromkeys(own + added))


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
        out: Dict[Any, Any] = {}
        for k, v in value.items():
            ck = _clean(k, fn)
            if ck in out:
                raise LedgerRefused(f"clean makes two keys collide: {k!r} and {ck!r}")
            out[ck] = _clean(v, fn)
        return out
    if isinstance(value, (list, tuple)):
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
    clean = reader._config["clean"]
    if clean is not None:
        out = _clean(out, clean)
    if "at" not in out:
        out["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if "actor" not in out:
        out["actor"] = _actor(actor)
    _apply_refs(out, refs)
    validate = reader._config["validate"]
    if validate is not None:
        validate(out)
    if path is None:
        path = reader.ledger_path(name, reader.adapter_of(name), root)
    try:
        text = json.dumps(out, ensure_ascii=ensure_ascii, default=str, allow_nan=False)
    except ValueError as exc:
        raise LedgerRefused(f"row is not valid JSON: {exc}") from exc
    data = (text + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    try:
        fd = os.open(path, flags, 0o644)
    except FileNotFoundError:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, flags, 0o644)
    try:
        n = os.write(fd, data)
    finally:
        os.close(fd)
    if n != len(data):
        raise OSError(f"short write {n}/{len(data)} to {path}")
    return out
