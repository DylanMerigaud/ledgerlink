"""Read two synthetic ledgers through one envelope, tail a new line, look a row up by key."""

import json
import os
import tempfile

import ledgerlink

root = tempfile.mkdtemp()
with open(os.path.join(root, "deploys.jsonl"), "w") as fh:
    for row in (
        {"ts": "2026-11-18 09:00:00", "svc": "api", "id": 1, "result": "ok"},
        {"ts": "2026-11-18T10:00:00+01:00", "svc": "web", "id": 2, "result": "failed"},
    ):
        fh.write(json.dumps(row) + "\n")
with open(os.path.join(root, "alerts.jsonl"), "w") as fh:
    fh.write(json.dumps({"epoch": 1763460000, "project": "web", "kind": "page", "n": 1}) + "\n")

adapters = {
    "deploys": {"at": ["ts"], "bet": ["svc"], "key": ["id"], "outcome": ["result"]},
    "alerts": {"at": ["epoch"], "bet": ["project"], "channel": ["kind"], "key": ["n"]},
}
ledgerlink.configure(adapters=adapters, root=root)

with ledgerlink.cache.Cache(os.path.join(root, "cache.sqlite")) as cache:
    for name in adapters:
        for env in ledgerlink.read(name, cache=cache):
            print(name, env["at"], env["bet"], env["line"], env["outcome"])
    with open(os.path.join(root, "deploys.jsonl"), "a") as fh:
        fh.write(json.dumps({"ts": "2026-11-18T11:00:00Z", "svc": "web", "id": 3}) + "\n")
    print("parsed after the append:", ledgerlink.refresh("deploys", cache=cache)["parsed"])
    print("latest web row:", ledgerlink.lookup("deploys", "3", cache=cache)["at"])
