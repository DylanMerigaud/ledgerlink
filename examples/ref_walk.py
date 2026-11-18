"""Declare two ref stores, link records across them and walk the graph."""

from ledgerlink import graph, refs

refs.define("ticket", r"\d+", hint="ticket:<integer id>")
refs.define("owner", r"[a-z]+", unresolvable="owners live in the directory, not read here")

tickets = {
    "1": {"title": "login fails", "status": "open", "refs": ["owner:ada", "ticket:2"]},
    "2": {"title": "retry the login", "status": "done", "refs": []},
}
refs.register("ticket", lambda r: tickets.get(r.key))


def backlinks(ref, record):
    # what points AT a ref is your knowledge: here, ticket 2 is blocked by ticket 1
    return [("blocks", "ticket:1")] if ref == "ticket:2" else []


for node in graph.walk("ticket:2", hops=2, backlinks=backlinks):
    print("  " * node["depth"] + node["ref"], "|", node["summary"], "|", node["reason"] or "")
