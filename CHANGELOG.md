# Changelog

## 0.1.0

First release.

- `read`, `lookup`, `refresh`, `envelope`, `configure`: one envelope over JSON Lines ledgers through an adapter table.
- `refs`: the `<store>:<key>` grammar with one built-in store (`ledger`) and `define` / `undefine` for your own.
- `cache.Cache`: the offset-tailing sqlite cache.
- `graph`: a read-only walk over the refs with injected back edges.
