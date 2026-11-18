"""The ref grammar: define, parse, resolve, unregister."""

import json
import re

import pytest

import ledgerlink
from ledgerlink import refs


@pytest.fixture
def grammar():
    refs.define("task", r"\d+", hint="task:<integer id>")
    refs.define("row", r"[^\s:/]+/[^\s:/]+", sep="/", hint="row:<project>/<channel>")
    refs.define("pop", re.compile(r"\S.*"), unresolvable="has no ledger of its own yet")


def test_builtin_store_only_by_default():
    assert refs.stores() == ("ledger",)
    with pytest.raises(ValueError, match="known stores: ledger"):
        refs.parse("task:1")


def test_parse_every_store(grammar):
    assert refs.parse("task:12") == ("task", "12", ("12",))
    assert refs.parse("row:p/send") == ("row", "p/send", ("p", "send"))
    assert refs.parse("ledger:deploy-log:p:send").parts == ("deploy-log:p:send",)
    assert refs.parse("ledger:a.b:k").store == "ledger"
    assert refs.stores() == ("ledger", "task", "row", "pop")


def test_unknown_store_names_the_known_ones(grammar):
    with pytest.raises(ValueError, match=r"unknown ref store 'nope'.*ledger, task, row, pop"):
        refs.parse("nope:1")


@pytest.mark.parametrize(
    "bad", ["task:x", "task:", "task:1 2", "row:a", "row:a/b/c", "ledger:noname", "ledger::k"]
)
def test_bad_shape_is_refused(grammar, bad):
    with pytest.raises(ValueError, match=r"bad key|unknown"):
        refs.parse(bad)


def test_bad_key_error_shows_the_hint(grammar):
    with pytest.raises(ValueError, match=r"want task:<integer id>.*task:x"):
        refs.parse("task:x")


def test_pattern_must_match_the_whole_key(grammar):
    with pytest.raises(ValueError):
        refs.parse("task:12abc")


@pytest.mark.parametrize("bad", [None, 3, "nocolon", ""])
def test_not_a_ref(bad):
    with pytest.raises(ValueError, match="not a ref"):
        refs.parse(bad)


def test_default_hint_when_none_given():
    refs.define("thing", r"\w+")
    with pytest.raises(ValueError, match=r"want thing:<key>"):
        refs.parse("thing:!")


def test_resolve_uses_the_registered_resolver_and_gives_refs(grammar):
    refs.register("task", lambda r: {"title": f"t{r.key}", "refs": ["row:p/send"]})
    assert refs.resolve("task:7") == {"title": "t7", "refs": ["row:p/send"]}
    assert refs.resolve(refs.parse("task:7"))["title"] == "t7"


def test_record_without_refs_gets_an_empty_list(grammar):
    refs.register("task", lambda r: {"title": "t"})
    assert refs.resolve("task:1") == {"title": "t", "refs": []}


def test_resolver_record_is_copied(grammar):
    rec = {"title": "t", "refs": ["task:2"]}
    refs.register("task", lambda r: rec)
    out = refs.resolve("task:1")
    out["refs"].append("x")
    assert rec["refs"] == ["task:2"]


def test_missing_record_returns_none_with_a_reason(grammar):
    refs.register("task", lambda r: None)
    assert refs.resolve_with_reason("task:9") == (None, "task:9 not found")
    assert refs.resolve("task:9") is None


def test_unresolvable_store_reason(grammar):
    assert refs.resolve_with_reason("pop:home") == (None, "has no ledger of its own yet")
    assert refs.resolve_with_reason("task:1") == (None, "no resolver registered for 'task'")


def test_unregister_one_and_all(grammar):
    refs.register("task", lambda r: {"a": 1})
    refs.register("row", lambda r: {"a": 2})
    refs.unregister("task")
    assert refs.resolve("task:1") is None and refs.resolve("row:a/b") == {"a": 2, "refs": []}
    refs.unregister()
    assert refs.resolve("row:a/b") is None
    refs.unregister("never-registered")


def test_register_refuses_an_unknown_store():
    with pytest.raises(ValueError, match="unknown ref store 'task'"):
        refs.register("task", lambda r: None)


def test_format_ref_checks_the_key(grammar):
    assert refs.format_ref("task", "5") == "task:5"
    with pytest.raises(ValueError):
        refs.format_ref("task", "five")


def test_undefine_drops_the_store_and_its_resolver(grammar):
    refs.register("task", lambda r: {})
    refs.undefine("task")
    assert "task" not in refs.stores()
    with pytest.raises(ValueError, match="unknown ref store"):
        refs.parse("task:1")
    with pytest.raises(ValueError, match="unknown ref store"):
        refs.undefine("task")
    refs.define("task", r"\d+")
    assert refs.resolve("task:1") is None  # the old resolver did not come back


def test_define_replaces_a_declaration(grammar):
    refs.define("task", r"[a-z]+")
    assert refs.parse("task:abc").key == "abc"
    with pytest.raises(ValueError):
        refs.parse("task:1")


@pytest.mark.parametrize("bad", ["", "a:b", "1x", "has space"])
def test_define_refuses_a_bad_store_name(bad):
    with pytest.raises(ValueError, match="bad store name"):
        refs.define(bad, r".*")


def test_the_builtin_cannot_be_redefined_or_removed():
    with pytest.raises(ValueError, match="built in"):
        refs.define("ledger", r".*")
    with pytest.raises(ValueError, match="built in"):
        refs.undefine("ledger")


def test_ledger_store_resolves_through_lookup(ledgers, cache):
    ad = {"deploys": {"at": ["at"], "key": ["id"], "refs": ["refs"]}}
    rows = [{"at": "1", "id": "a", "refs": ["ledger:deploys:b"]}, {"at": "2", "id": "b"}]
    (ledgers / "deploys.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    ledgerlink.configure(adapters=ad, root=str(ledgers))
    rec = refs.resolve("ledger:deploys:a")
    assert rec["id"] == "a" and rec["refs"] == ["ledger:deploys:b"]
    assert refs.resolve_with_reason("ledger:deploys:zzz") == (None, "ledger:deploys:zzz not found")
    assert refs.resolve_with_reason("ledger:ghost:k")[0] is None


def test_a_registered_ledger_resolver_wins_and_the_builtin_returns_after_unregister(ledgers):
    refs.register("ledger", lambda r: {"mine": r.key})
    assert refs.resolve("ledger:x:y")["mine"] == "x:y"
    refs.unregister("ledger")
    assert refs.resolve("ledger:x:y") is None
