# Changelog

## 0.2.0

- `append(name, row, *, actor, refs, root, path, ensure_ascii)`: the writer. One JSON line per call, written with a single `os.write` on an `O_APPEND` descriptor. Adds `at` and `actor` only when the row has none, merges `refs`, keeps every caller field in order.
- `LedgerRefused` (a `ValueError`): raised, with nothing written, on a bad ref or when `validate` refuses.
- `configure(actor_env, clean, validate)`: the env var the actor is read from (default `LEDGERLINK_ACTOR`), a function applied to every string of a written row, and a final check on it. Existing calls keep working; passing `None` explicitly now clears a setting.
- `clean` runs on the row's own fields before `at`, `actor` and `refs` are added: the `actor` and `refs` keyword arguments and the env actor are written as given.
- A short `os.write` raises `OSError`; the partial line it left is not rolled back.
- `reader.adapter_of(name)`: the adapter lookup shared by the reader and the writer.

## 0.1.0

First release.

- `read`, `lookup`, `refresh`, `envelope`, `configure`: one envelope over JSON Lines ledgers through an adapter table.
- `refs`: the `<store>:<key>` grammar with one built-in store (`ledger`) and `define` / `undefine` for your own.
- `cache.Cache`: the offset-tailing sqlite cache.
- `graph`: a read-only walk over the refs with injected back edges.
