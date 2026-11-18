"""The ref grammar: a typed string `<store>:<key>` naming one record in one store.

One store is built in: `ledger:<name>:<key>`, the record of the ledger `name` whose key is `key`
(through `ledgerlink.lookup` and the adapter table installed with `ledgerlink.configure`). Every
other store is yours: declare it with `define`.

    refs.define("task", r"\\d+", hint="task:<integer id>")
    refs.define("row", r"[^\\s:/]+/[^\\s:/]+", sep="/", hint="row:<project>/<channel>")
    refs.register("task", lambda ref: {"title": "...", "refs": ["row:p/send"]})
    refs.resolve("task:7")

`parse` checks the shape of the key per store (the pattern must match the whole key) and refuses
an unknown store (ValueError naming the known ones). `resolve` hands the record to the resolver
registered for the store; the record carries its own `refs` (a list of refs). A store with no
resolver yet is known and unresolvable: `resolve` returns None and `resolve_with_reason` says why
(the `unresolvable` text given to `define`, else a default).

`stores()` returns the names of the known stores at the time of the call (a snapshot tuple, the
built-in first, then in definition order).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, NamedTuple, Optional, Tuple, Union

__all__ = [
    "Ref",
    "define",
    "format_ref",
    "parse",
    "register",
    "resolve",
    "resolve_with_reason",
    "stores",
    "undefine",
    "unregister",
]

BUILTIN = "ledger"
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
_LEDGER_KEY = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*:\S.*")


class Ref(NamedTuple):
    store: str
    key: str
    parts: Tuple[str, ...]


class _Store(NamedTuple):
    pattern: re.Pattern[str]
    sep: Optional[str]
    hint: str
    unresolvable: Optional[str]


Resolver = Callable[[Ref], Optional[Dict[str, Any]]]

_stores: Dict[str, _Store] = {
    BUILTIN: _Store(_LEDGER_KEY, None, "ledger:<name>:<key>", None),
}
_resolvers: Dict[str, Resolver] = {}


def define(
    store: str,
    pattern: Union[str, re.Pattern[str]],
    sep: Optional[str] = None,
    hint: str = "",
    unresolvable: Optional[str] = None,
) -> None:
    """Declare a ref store. `pattern` is a regex the whole key must match, `sep` splits the key
    into `Ref.parts` (else the parts are `(key,)`), `hint` is the shape shown in errors, and
    `unresolvable` is the reason `resolve_with_reason` gives while no resolver is registered.
    Defining a store again replaces its declaration. The built-in `ledger` cannot be redefined."""
    if not isinstance(store, str) or not _NAME.fullmatch(store):
        raise ValueError(f"bad store name (letters, digits, - and _, no colon): {store!r}")
    if store == BUILTIN:
        raise ValueError(f"the store {BUILTIN!r} is built in and cannot be redefined")
    compiled = re.compile(pattern) if isinstance(pattern, str) else pattern
    _stores[store] = _Store(compiled, sep, hint or f"{store}:<key>", unresolvable)


def undefine(store: str) -> None:
    """Forget a store declared with `define`, and its resolver. The built-in cannot be removed."""
    if store == BUILTIN:
        raise ValueError(f"the store {BUILTIN!r} is built in and cannot be removed")
    if store not in _stores:
        raise ValueError(f"unknown ref store {store!r}; known stores: {', '.join(stores())}")
    del _stores[store]
    _resolvers.pop(store, None)


def stores() -> Tuple[str, ...]:
    """The names of the known stores."""
    return tuple(_stores)


def _unknown(store: str) -> ValueError:
    return ValueError(f"unknown ref store {store!r}; known stores: {', '.join(stores())}")


def parse(ref: Any) -> Ref:
    """Ref(store, key, parts). ValueError on a non string, an unknown store or a bad key."""
    if not isinstance(ref, str) or ":" not in ref:
        raise ValueError(f"not a ref (want <store>:<key>): {ref!r}")
    store, key = ref.split(":", 1)
    if store not in _stores:
        raise _unknown(store)
    spec = _stores[store]
    if not spec.pattern.fullmatch(key):
        raise ValueError(f"bad key for {store!r} (want {spec.hint}): {ref!r}")
    parts = tuple(key.split(spec.sep)) if spec.sep else (key,)
    return Ref(store, key, parts)


def format_ref(store: str, key: str) -> str:
    """The canonical string of a store and a key, checked by parse."""
    ref = f"{store}:{key}"
    parse(ref)
    return ref


def register(store: str, fn: Resolver) -> None:
    """Install the resolver of a store: fn(Ref) -> dict or None."""
    if store not in _stores:
        raise _unknown(store)
    _resolvers[store] = fn


def unregister(store: Optional[str] = None) -> None:
    """Drop one resolver, or all (tests). The built-in ledger resolver is the fallback and stays."""
    if store is None:
        _resolvers.clear()
    else:
        _resolvers.pop(store, None)


def _ledger(ref: Ref) -> Optional[Dict[str, Any]]:
    from . import reader

    name, key = ref.key.split(":", 1)
    env = reader.lookup(name, key)
    if env is None:
        return None
    return dict(env["raw"], refs=list(env["refs"]))


def resolve_with_reason(ref: Union[str, Ref]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(record, reason). Record is a dict carrying `refs` (a list), or None with the reason."""
    parsed = parse(ref) if not isinstance(ref, Ref) else ref
    fn = _resolvers.get(parsed.store)
    if fn is None and parsed.store == BUILTIN:
        fn = _ledger
    if fn is None:
        spec = _stores.get(parsed.store)
        return None, (spec and spec.unresolvable) or f"no resolver registered for {parsed.store!r}"
    record = fn(parsed)
    if record is None:
        return None, f"{parsed.store}:{parsed.key} not found"
    record = dict(record)
    record["refs"] = list(record.get("refs") or [])
    return record, None


def resolve(ref: Union[str, Ref]) -> Optional[Dict[str, Any]]:
    """The record of a ref (a dict with its own `refs`), or None (see resolve_with_reason)."""
    return resolve_with_reason(ref)[0]
