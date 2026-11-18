"""The read only walk over refs, with injected back edges and a node cap."""

import pytest

from ledgerlink import graph, refs


@pytest.fixture
def world():
    refs.define("node", r"\w+", hint="node:<name>")
    edges = {"a": ["node:b", "node:c"], "b": ["node:d"], "c": ["node:a"], "d": []}

    def resolver(r):
        if r.key not in edges:
            return None
        return {"name": r.key, "status": "ok", "refs": edges[r.key]}

    refs.register("node", resolver)
    return edges


def test_forward_edges_and_a_visited_set_stop_cycles(world):
    nodes = graph.walk("node:a", 5)
    assert [n["ref"] for n in nodes] == ["node:a", "node:b", "node:c", "node:d"]
    assert [n["depth"] for n in nodes] == [0, 1, 1, 2]
    assert nodes[1]["via"] == "node:a" and nodes[1]["label"] == "node"
    assert nodes[0]["summary"] == "a | ok"


def test_hops_limit_the_depth(world):
    assert [n["ref"] for n in graph.walk("node:a", 0)] == ["node:a"]
    assert [n["ref"] for n in graph.walk("node:a", 1)] == ["node:a", "node:b", "node:c"]


def test_injected_back_edges_are_followed(world):
    def backlinks(ref, record):
        return [("pointed-by", "node:z")] if ref == "node:d" else []

    nodes = graph.walk("node:a", 5, backlinks=backlinks)
    z = next(n for n in nodes if n["ref"] == "node:z")
    assert z["via"] == "node:d" and z["label"] == "pointed-by"
    assert z["record"] is None and z["reason"] == "node:z not found"


def test_a_node_without_a_record_is_still_expanded_by_back_edges(world):
    def backlinks(ref, record):
        return [("back", "node:b")] if ref == "node:ghost" else []

    nodes = graph.walk("node:ghost", 1, backlinks=backlinks)
    assert [n["ref"] for n in nodes] == ["node:ghost", "node:b"]
    assert nodes[0]["record"] is None


def test_neighbours_dedupe_and_never_list_the_ref_itself(world):
    got = graph.neighbours("node:a", backlinks=lambda r, rec: [("x", "node:b"), ("x", "node:a")])
    assert got == [("node", "node:b"), ("node", "node:c")]


def test_a_ref_that_does_not_parse_is_a_node_with_a_reason(world):
    (node,) = graph.walk("bogus:1", 1)
    assert node["record"] is None and "unknown ref store" in node["reason"]


def test_node_cap_truncates(world):
    refs.define("n", r"\d+")
    refs.register("n", lambda r: {"refs": [f"n:{int(r.key) * 2 + 1}", f"n:{int(r.key) * 2 + 2}"]})
    nodes = graph.walk("n:0", 10, node_cap=5)
    assert len(nodes) == 6 and nodes[-1].get("truncated", 0) >= 1
    assert all("ref" in n for n in nodes[:-1])
    assert len(graph.walk("n:0", 10)) == graph.NODE_CAP + 1


def test_custom_summary(world):
    nodes = graph.walk("node:a", 0, summary=lambda rec: "S")
    assert nodes[0]["summary"] == "S"


def test_summarize_defaults():
    assert graph.summarize(None) == "(no record)"
    assert graph.summarize({"title": "T", "state": "open", "at": "now"}) == "T | open | now"
    assert graph.summarize({"op": "x" * 300}) == "x" * 100
