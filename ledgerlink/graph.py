"""A read only walk over the refs of the records: forward edges and injected back edges.

Stdlib only. A record's forward edges are its own `refs` (what `refs.resolve` returns). What points
AT a record is consumer knowledge, so the consumer injects `backlinks(ref, record)` (the record
may be None), a callable returning `(label, ref)` pairs already capped per kind by the provider.
Nothing here reads a store.

    neighbours(ref, backlinks=None)            [(label, ref)], forward first, deduplicated
    walk(ref, hops, backlinks=None, ...)       breadth first, a visited set, a node cap
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import refs as _refs

NODE_CAP = 60

Backlinks = Callable[[str, Optional[Dict[str, Any]]], Optional[Iterable[Tuple[str, str]]]]


def _resolve(ref: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(record or None, reason or None). A ref that does not parse is no record, never a raise."""
    try:
        return _refs.resolve_with_reason(ref)
    except ValueError as err:
        return None, str(err)


def neighbours(
    ref: str,
    backlinks: Optional[Backlinks] = None,
    record: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str]]:
    """[(label, ref)]: the record's own refs (labelled by their store), then the injected back
    edges. Deduplicated by ref (the first label wins), the ref itself never listed."""
    if record is None:
        record = _resolve(ref)[0]
    out: List[Tuple[str, str]] = []
    seen = {ref}
    pairs = [(r.split(":", 1)[0], r) for r in (record or {}).get("refs") or ()]
    if backlinks is not None:
        pairs.extend(backlinks(ref, record) or ())
    for label, other in pairs:
        if other not in seen:
            seen.add(other)
            out.append((label, other))
    return out


def summarize(record: Optional[Dict[str, Any]]) -> str:
    """A one line default summary: what, state, at."""
    if not record:
        return "(no record)"
    what = next(
        (
            str(record[k])
            for k in ("name", "event", "key", "label", "title", "slug", "op")
            if record.get(k)
        ),
        "",
    )
    state = next((str(record[k]) for k in ("state", "status", "outcome") if record.get(k)), "")
    at = next((str(record[k]) for k in ("at", "updated_at", "created_at") if record.get(k)), "")
    return " | ".join(p[:100] for p in (what, state, at) if p)


def walk(
    ref: str,
    hops: int,
    backlinks: Optional[Backlinks] = None,
    summary: Callable[[Optional[Dict[str, Any]]], str] = summarize,
    node_cap: int = NODE_CAP,
) -> List[Dict[str, Any]]:
    """Breadth first from `ref`, `hops` hops out. Returns a list of nodes in visit order:
    {"ref", "depth", "via" (the ref it was reached from or None), "label", "record", "summary",
    "reason" (why there is no record, else None)}. A ref with no record is still a node and is
    still expanded through the back edges. A visited set stops cycles; past `node_cap` nodes the
    walk stops and the last node is {"truncated": N more}."""
    nodes: List[Dict[str, Any]] = []
    seen = {ref}
    queue: deque[Tuple[str, int, Optional[str], Optional[str]]] = deque([(ref, 0, None, None)])
    while queue:
        cur, depth, via, label = queue.popleft()
        if len(nodes) >= node_cap:
            nodes.append({"truncated": len(queue) + 1})
            break
        record, reason = _resolve(cur)
        nodes.append(
            {
                "ref": cur,
                "depth": depth,
                "via": via,
                "label": label,
                "record": record,
                "summary": summary(record),
                "reason": None if record else reason,
            }
        )
        if depth >= hops:
            continue
        for lab, other in neighbours(cur, backlinks, record):
            if other not in seen:
                seen.add(other)
                queue.append((other, depth + 1, cur, lab))
    return nodes
