import json
import sys
import threading

import pytest

import ledgerlink
from ledgerlink import refs


def lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_caller_fields_kept_in_order(ledgers):
    row = {"z": 1, "a": {"n": [1, 2]}, "m": "x"}
    out = ledgerlink.append("l", row, root=str(ledgers))
    assert list(out)[:3] == ["z", "a", "m"]
    assert out["a"] == {"n": [1, 2]}
    assert list(lines(ledgers / "l.jsonl")[0])[:3] == ["z", "a", "m"]
    assert "at" not in row and "actor" not in row


def test_at_added_only_when_absent(ledgers):
    out = ledgerlink.append("l", {"k": 1}, root=str(ledgers))
    assert out["at"].endswith("+00:00") and len(out["at"]) == 25
    assert ledgerlink.append("l", {"at": "x"}, root=str(ledgers))["at"] == "x"


def test_actor_precedence(ledgers, monkeypatch):
    r = str(ledgers)
    monkeypatch.setattr(sys, "argv", ["/bin/tool.py"])
    assert ledgerlink.append("l", {}, root=r)["actor"] == "script:tool"
    monkeypatch.setattr(sys, "argv", [""])
    assert ledgerlink.append("l", {}, root=r)["actor"] == "script:python"
    monkeypatch.setenv("LEDGERLINK_ACTOR", "env")
    assert ledgerlink.append("l", {}, root=r)["actor"] == "env"
    ledgerlink.configure(actor_env="MY_ACTOR")
    assert ledgerlink.append("l", {}, root=r)["actor"] == "script:python"
    monkeypatch.setenv("MY_ACTOR", "mine")
    assert ledgerlink.append("l", {}, root=r)["actor"] == "mine"
    assert ledgerlink.append("l", {}, actor="kw", root=r)["actor"] == "kw"
    assert ledgerlink.append("l", {"actor": "row"}, actor="kw", root=r)["actor"] == "row"


def test_refs_merge_and_dedupe(ledgers):
    out = ledgerlink.append(
        "l", {"refs": ["a:1", "b:2"]}, refs=["b:2", "c:3", "a:1"], root=str(ledgers)
    )
    assert out["refs"] == ["a:1", "b:2", "c:3"]
    assert "refs" not in ledgerlink.append("l", {}, root=str(ledgers))


@pytest.mark.parametrize("bad", ["nocolon", "a:", "a:b c", "1a:x", 5, ":x"])
def test_bad_ref_refused_nothing_written(ledgers, bad):
    with pytest.raises(ledgerlink.LedgerRefused):
        ledgerlink.append("l", {"k": 1}, refs=["ok:1", bad], root=str(ledgers))
    assert not (ledgers / "l.jsonl").exists()
    assert issubclass(ledgerlink.LedgerRefused, ValueError)


def test_defined_store_goes_through_parse(ledgers):
    refs.define("task", r"\d+", hint="task:<integer id>")
    assert ledgerlink.append("l", {}, refs=["task:7"], root=str(ledgers))["refs"] == ["task:7"]
    with pytest.raises(ledgerlink.LedgerRefused, match="task:<integer id>"):
        ledgerlink.append("l", {}, refs=["task:abc"], root=str(ledgers))
    assert len(lines(ledgers / "l.jsonl")) == 1


def test_clean_is_recursive_on_keys_and_values(ledgers):
    ledgerlink.configure(clean=lambda s: s.replace("bad", "ok"))
    out = ledgerlink.append(
        "l", {"bad": "bad1", "n": {"bad2": ["bad3", 4]}}, actor="bad", root=str(ledgers)
    )
    assert out["ok"] == "ok1" and out["n"] == {"ok2": ["ok3", 4]} and out["actor"] == "ok"
    assert lines(ledgers / "l.jsonl")[0] == out


def test_validate_can_refuse(ledgers):
    def validate(row):
        if "op" not in row:
            raise ledgerlink.LedgerRefused("op required")

    ledgerlink.configure(validate=validate)
    with pytest.raises(ledgerlink.LedgerRefused, match="op required"):
        ledgerlink.append("l", {}, root=str(ledgers))
    assert not (ledgers / "l.jsonl").exists()
    ledgerlink.append("l", {"op": "x"}, root=str(ledgers))
    assert len(lines(ledgers / "l.jsonl")) == 1


def test_one_line_per_call_and_ensure_ascii(ledgers):
    ledgerlink.append("l", {"w": "café"}, root=str(ledgers))
    ledgerlink.append("l", {"w": "café"}, root=str(ledgers), ensure_ascii=True)
    text = (ledgers / "l.jsonl").read_text(encoding="utf-8")
    assert len(text.splitlines()) == 2 and text.endswith("\n")
    assert "café" in text.splitlines()[0] and "\\u00e9" in text.splitlines()[1]


def test_default_serializer_for_unknown_types(ledgers):
    from decimal import Decimal

    assert ledgerlink.append("l", {"d": Decimal("1.5")}, root=str(ledgers))["d"] == Decimal("1.5")
    assert lines(ledgers / "l.jsonl")[0]["d"] == "1.5"


def test_readable_back_with_actor_and_refs(ledgers):
    ledgerlink.configure(
        adapters={"l": {"at": ["at"], "actor": ["actor"], "refs": ["refs"], "key": ["id"]}},
        root=str(ledgers),
    )
    ledgerlink.append("l", {"id": 1}, actor="me", refs=["x:1"])
    (env,) = list(ledgerlink.read("l", cache=False))
    assert env["actor"] == "me" and env["refs"] == ["x:1"] and env["key"] == "1"
    assert env["at"] and env["raw"]["id"] == 1


def test_adapter_path_and_explicit_path(tmp_path):
    target = tmp_path / "deep" / "er" / "a.jsonl"
    ledgerlink.configure(adapters={"l": {"path": str(target)}})
    ledgerlink.append("l", {"k": 1})
    assert len(lines(target)) == 1
    other = tmp_path / "o" / "b.jsonl"
    ledgerlink.append("l", {"k": 2}, path=str(other))
    assert len(lines(other)) == 1 and len(lines(target)) == 1


def test_root_from_config_creates_parent(tmp_path):
    ledgerlink.configure(root=str(tmp_path / "new" / "dir"))
    ledgerlink.append("l", {"k": 1})
    assert len(lines(tmp_path / "new" / "dir" / "l.jsonl")) == 1


def test_concurrent_appends_never_interleave(ledgers):
    def work(t):
        for i in range(200):
            ledgerlink.append("l", {"t": t, "i": i, "pad": "x" * 500}, root=str(ledgers))

    threads = [threading.Thread(target=work, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = lines(ledgers / "l.jsonl")
    assert len(rows) == 800
    assert {(r["t"], r["i"]) for r in rows} == {(t, i) for t in range(4) for i in range(200)}
