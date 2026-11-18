"""ledgerlink: one envelope over heterogeneous JSON Lines ledgers, a ref grammar, a sqlite cache.

Stdlib only. The consumer injects what is its own (adapter table, ledger directory, ref stores
and resolvers) through `configure`, `refs.define` and `refs.register`.

    ledgerlink.read(name, since=None, ...)   rows of a ledger as the envelope
    ledgerlink.lookup(name, value, by="key") the latest row of a ledger for a key or id
    ledgerlink.refs.define(store, pattern)   declare a ref store; parse / resolve / register
    ledgerlink.cache.Cache                   the offset tailing sqlite cache
    ledgerlink.graph.walk(ref, hops)         a read only walk over the refs
"""

from . import cache, graph, refs
from .reader import ENVELOPE_KEYS, ENVELOPE_VERSION, configure, envelope, lookup, read, refresh

__version__ = "0.1.0"

__all__ = [
    "ENVELOPE_KEYS",
    "ENVELOPE_VERSION",
    "cache",
    "configure",
    "envelope",
    "graph",
    "lookup",
    "read",
    "refresh",
    "refs",
]
