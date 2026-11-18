# ledgerlink

One envelope over many heterogeneous JSON Lines ledgers, a ref grammar you extend, an
offset-tailing sqlite cache and a read-only walk over the refs.

- **One envelope.** Every row of every ledger becomes
  `{at, actor, bet, line, key, op, outcome, refs, why, raw}`, through an adapter table that maps
  your field names to those keys (dotted names reach into nested objects). `bet` is the project
  (or bet) the row belongs to, `line` is `<bet>/<channel>`.
- **A ref grammar.** `<store>:<key>` names one record in one store. One store is built in
  (`ledger:<name>:<key>`); you declare your own with `refs.define`, give each a resolver, and
  `refs.resolve` hands back the record with its own `refs`.
- **A sqlite cache that tails by offset.** A warm read parses only the bytes appended since the
  last one; a truncated or replaced file is re-read from zero.
- **A read-only walk.** `graph.walk` follows the refs of the records breadth first, with a
  visited set, a node cap and back edges you inject.

Python 3.9+, standard library only.

## Install

```bash
pip install ledgerlink
```

## Example

```python
import json, os, tempfile
import ledgerlink

root = tempfile.mkdtemp()
with open(os.path.join(root, "deploys.jsonl"), "w") as fh:
    fh.write(
        json.dumps({"ts": "2026-11-18 09:00:00", "svc": "api", "id": 7, "result": "ok"}) + "\n"
    )
    fh.write(
        json.dumps(
            {"ts": "2026-11-18 10:00:00", "svc": "api", "id": 8, "result": "failed", "after": 7}
        )
        + "\n"
    )

adapters = {"deploys": {"at": ["ts"], "bet": ["svc"], "key": ["id"], "outcome": ["result"]}}
ledgerlink.configure(adapters=adapters, root=root)
cache = os.path.join(root, "cache.sqlite")  # default: ~/.cache/ledgerlink/ledgerlink.sqlite
with ledgerlink.cache.Cache(cache) as c:
    rows = list(ledgerlink.read("deploys", since="2026-11-18T09:30:00", cache=c))
    print(rows[0]["key"], rows[0]["outcome"])  # 8 failed
    print(ledgerlink.lookup("deploys", "7", cache=c)["at"])  # 2026-11-18T09:00:00
```

Declare a store and walk it:

```python
from ledgerlink import graph, refs

refs.define("task", r"\d+", hint="task:<integer id>")
tasks = {"1": ["task:2"], "2": ["task:3"], "3": []}
refs.register("task", lambda r: {"title": f"task {r.key}", "refs": tasks[r.key]})

for node in graph.walk("task:1", hops=2):
    print(node["depth"], node["ref"], node["summary"])
```

`refs.define(store, pattern, sep=None, hint="", unresolvable=None)`: `pattern` must match the
whole key, `sep` splits the key into `Ref.parts`, `hint` is shown in errors, `unresolvable` is
the reason `resolve_with_reason` gives while no resolver is registered. `refs.stores()` lists
the known stores, `refs.undefine(store)` forgets one.

The ledger directory is `configure(root=...)`, else `LEDGERLINK_ROOT`, else the current
directory. The cache file is `LEDGERLINK_CACHE`, else
`$XDG_CACHE_HOME/ledgerlink/ledgerlink.sqlite` (fallback `~/.cache/ledgerlink/ledgerlink.sqlite`).
It is a cache: safe to delete.

## What it does not do

- No writer: it never appends to or changes a ledger.
- No schema enforcement: a row that does not fit the adapter gets `None` fields, and `raw` is
  always the row as written.
- No network and no daemon: it reads files when you call it.
- No time zone guessing: a time with a zone is normalized to UTC, a zone-less one is kept as
  written, and `since`/`until` compare `at` as text. Keep a ledger's times in one form.

## Contributing

Changes are made in this repository, released as a new version, and the projects that use
ledgerlink bump their pin. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
