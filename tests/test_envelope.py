"""The reader, the envelope and the cache."""

import json
import os

import pytest

import ledgerlink
from ledgerlink import cache as cache_mod


def _write(path, rows, mode="w"):
    with open(path, mode) as fh:
        for r in rows:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


def test_envelope_maps_the_fields_of_an_adapter():
    ad = {
        "at": ["ts"],
        "bet": ["project"],
        "channel": ["channel"],
        "key": ["project", "item_id"],
        "op": ["op"],
        "outcome": ["verdict", "after.passed"],
        "why": ["reason"],
        "refs": ["refs"],
    }
    row = {
        "ts": "2026-11-18 10:00:00",
        "project": "p",
        "channel": "send",
        "item_id": 7,
        "op": "sent",
        "after": {"passed": False},
        "refs": ["ticket:1"],
        "reason": "r",
    }
    env = ledgerlink.envelope(row, ad)
    assert env == {
        "at": "2026-11-18T10:00:00",
        "actor": "row:p/send",
        "bet": "p",
        "line": "p/send",
        "key": "p:7",
        "op": "sent",
        "outcome": "false",
        "refs": ["ticket:1"],
        "why": "r",
        "raw": row,
    }
    assert list(env) == list(ledgerlink.ENVELOPE_KEYS)


def test_envelope_keys_are_the_contract():
    assert ledgerlink.ENVELOPE_KEYS == (
        "at",
        "actor",
        "bet",
        "line",
        "key",
        "op",
        "outcome",
        "refs",
        "why",
        "raw",
    )


def test_first_non_empty_field_wins_and_dotted_names_reach_in():
    ad = {"at": ["at"], "outcome": ["missing", "", "a.b.c", "z"]}
    env = ledgerlink.envelope({"at": "t", "a": {"b": {"c": "deep"}}, "z": "no"}, ad)
    assert env["outcome"] == "deep"
    assert ledgerlink.envelope({"at": "t", "a": 5}, ad)["outcome"] is None


def test_key_is_none_unless_every_field_is_present():
    env = ledgerlink.envelope({"a": 1}, {"key": ["a", "b"]})
    assert env["key"] is None
    assert ledgerlink.envelope({"a": 1, "b": "x"}, {"key": ["a", "b"]})["key"] == "1:x"


def test_an_explicit_line_field_and_actor():
    ad = {"line": ["where"], "actor": ["who"], "bet": ["b"], "channel": ["c"]}
    env = ledgerlink.envelope({"where": "x/y", "who": "bot", "b": "b", "c": "c"}, ad)
    assert env["line"] == "x/y" and env["actor"] == "bot"
    env = ledgerlink.envelope({"where": "x/y"}, ad)
    assert env["actor"] == "row:x/y"


def test_refs_field_takes_a_string_or_a_list():
    ad = {"refs": ["refs", "ref"]}
    env = ledgerlink.envelope({"refs": ["a:1", "", "b:2"], "ref": "c:3"}, ad)
    assert env["refs"] == ["a:1", "b:2", "c:3"]


@pytest.mark.parametrize(
    "value, want",
    [
        (0, "1970-01-01T00:00:00Z"),
        (1763460000.5, "2025-11-18T10:00:00Z"),
        ("2026-11-18 10:00:00", "2026-11-18T10:00:00"),
        ("2026-11-18T10:00:00Z", "2026-11-18T10:00:00Z"),
        ("2026-11-18T12:00:00+02:00", "2026-11-18T10:00:00Z"),
        ("2026-11-18T12:00:00.250000+0200", "2026-11-18T10:00:00Z"),
        ("2026-11-18", "2026-11-18"),
    ],
)
def test_at_variants(value, want):
    assert ledgerlink.envelope({"ts": value}, {"at": ["ts"]})["at"] == want


def test_at_missing_or_unparsable():
    assert ledgerlink.envelope({"x": 1}, {"at": ["ts"]})["at"] is None
    assert ledgerlink.envelope({"ts": 1e30}, {"at": ["ts"]})["at"] is None


def test_no_adapter_reads_at_and_raw_only(ledgers, cache):
    _write(ledgers / "z.jsonl", [{"at": "2026-01-01T00:00:00Z", "bet": "b", "op": "x"}])
    (env,) = ledgerlink.read("z", adapters={}, root=str(ledgers), cache=cache)
    assert env["at"] == "2026-01-01T00:00:00Z" and env["raw"]["op"] == "x"
    assert env["bet"] is None and env["op"] is None


def test_read_streams_without_cache_and_skips_bad_lines(ledgers):
    _write(ledgers / "z.jsonl", [{"at": "2026-01-01"}, "not json", "[1]", "", {"at": "2026-01-03"}])
    got = list(ledgerlink.read("z", adapters={}, root=str(ledgers), cache=False))
    assert [e["at"] for e in got] == ["2026-01-01", "2026-01-03"]


def test_since_until_and_limit(ledgers, cache):
    _write(ledgers / "z.jsonl", [{"at": f"2026-01-0{i} 00:00:00"} for i in range(1, 6)])
    kw = {"adapters": {}, "root": str(ledgers), "cache": cache}
    assert len(list(ledgerlink.read("z", since="2026-01-03", **kw))) == 3
    both = list(
        ledgerlink.read("z", since="2026-01-02T00:00:00", until="2026-01-03T00:00:00", **kw)
    )
    assert len(both) == 2
    assert len(list(ledgerlink.read("z", limit=2, **kw))) == 2
    nocache = {"cache": False, "adapters": {}, "root": str(ledgers)}
    assert len(list(ledgerlink.read("z", since="2026-01-03", **nocache))) == 3
    assert len(list(ledgerlink.read("z", until="2026-01-02T00:00:00", limit=1, **nocache))) == 1


def test_filters_on_bet_line_and_key(ledgers, cache):
    ad = {"z": {"at": ["at"], "bet": ["b"], "channel": ["c"], "key": ["k"]}}
    _write(
        ledgers / "z.jsonl",
        [
            {"at": "1", "b": "p", "c": "send", "k": "a"},
            {"at": "2", "b": "p", "c": "recv", "k": "b"},
            {"at": "3", "b": "q", "c": "send", "k": "a"},
        ],
    )
    for c in (cache, False):
        kw = {"adapters": ad, "root": str(ledgers), "cache": c}
        assert [e["at"] for e in ledgerlink.read("z", bet="p", **kw)] == ["1", "2"]
        assert [e["at"] for e in ledgerlink.read("z", line="q/send", **kw)] == ["3"]
        assert [e["at"] for e in ledgerlink.read("z", key="a", **kw)] == ["1", "3"]


def test_lookup_by_key_and_id_returns_the_latest(ledgers, cache):
    ad = {"j": {"at": ["at"], "key": ["name"], "id": ["job"], "op": ["op"]}}
    _write(
        ledgers / "j.jsonl",
        [
            {"at": "1", "name": "build", "job": "j1", "op": "start"},
            {"at": "2", "name": "build", "job": "j1", "op": "done"},
            {"at": "3", "name": "test", "job": "j2", "op": "start"},
        ],
    )
    kw = {"adapters": ad, "root": str(ledgers), "cache": cache}
    assert ledgerlink.lookup("j", "build", **kw)["op"] == "done"
    assert ledgerlink.lookup("j", "j2", by="id", **kw)["key"] == "test"
    assert ledgerlink.lookup("j", "nope", **kw) is None
    with pytest.raises(ValueError):
        ledgerlink.lookup("j", "build", by="what", **kw)


def test_warm_read_parses_only_the_new_bytes(ledgers, cache):
    p = ledgers / "z.jsonl"
    _write(p, [{"at": f"2026-01-0{i}"} for i in range(1, 4)])
    kw = {"adapters": {}, "root": str(ledgers), "cache": cache}
    assert ledgerlink.refresh("z", **kw)["parsed"] == 3
    assert ledgerlink.refresh("z", **kw) == {"parsed": 0, "bytes": 0, "reset": False}
    size = os.path.getsize(p)
    _write(p, [{"at": "2026-01-09"}], "a")
    stats = ledgerlink.refresh("z", **kw)
    assert stats["parsed"] == 1 and stats["bytes"] == os.path.getsize(p) - size
    assert [e["at"] for e in ledgerlink.read("z", **kw)][-1] == "2026-01-09"


def test_a_half_written_line_waits_for_its_newline(ledgers, cache):
    p = ledgers / "z.jsonl"
    _write(p, [{"at": "2026-01-01"}])
    with open(p, "a") as fh:
        fh.write('{"at": "2026-01-02"')
    kw = {"adapters": {}, "root": str(ledgers), "cache": cache}
    assert len(list(ledgerlink.read("z", **kw))) == 1
    with open(p, "a") as fh:
        fh.write("}\n")
    assert len(list(ledgerlink.read("z", **kw))) == 2


def test_truncated_or_replaced_file_is_re_read_from_zero(ledgers, cache):
    p = ledgers / "z.jsonl"
    _write(p, [{"at": f"2026-01-0{i}", "n": i} for i in range(1, 5)])
    kw = {"adapters": {}, "root": str(ledgers), "cache": cache}
    assert len(list(ledgerlink.read("z", **kw))) == 4
    _write(p, [{"at": "2026-02-01"}])  # truncated, shorter than the offset
    stats = ledgerlink.refresh("z", **kw)
    assert stats["reset"] and [e["at"] for e in ledgerlink.read("z", **kw)] == ["2026-02-01"]
    new = ledgers / "z.new"
    _write(new, [{"at": "2026-03-01"}, {"at": "2026-03-02"}])
    os.replace(new, p)  # another inode
    assert ledgerlink.refresh("z", **kw)["reset"]
    assert len(list(ledgerlink.read("z", **kw))) == 2


def test_a_deleted_file_empties_the_cache(ledgers, cache):
    p = ledgers / "z.jsonl"
    _write(p, [{"at": "1"}])
    kw = {"adapters": {}, "root": str(ledgers), "cache": cache}
    assert len(list(ledgerlink.read("z", **kw))) == 1
    p.unlink()
    assert list(ledgerlink.read("z", **kw)) == []


def test_a_new_envelope_version_rebuilds_the_cached_rows(ledgers, cache, monkeypatch):
    _write(ledgers / "z.jsonl", [{"at": "2026-01-01"}])
    kw = {"adapters": {}, "root": str(ledgers), "cache": cache}
    assert ledgerlink.refresh("z", **kw)["parsed"] == 1
    monkeypatch.setattr(ledgerlink.reader, "ENVELOPE_VERSION", ledgerlink.ENVELOPE_VERSION + 1)
    stats = ledgerlink.refresh("z", **kw)
    assert stats["reset"] and stats["parsed"] == 1


def test_changed_adapter_re_reads_from_zero(ledgers, cache):
    _write(ledgers / "z.jsonl", [{"at": "2026-01-01", "op": "a"}])
    kw = {"root": str(ledgers), "cache": cache}
    first = list(ledgerlink.read("z", adapters={"z": {"at": ["at"]}}, **kw))
    assert first[0]["op"] is None
    second = list(ledgerlink.read("z", adapters={"z": {"at": ["at"], "op": ["op"]}}, **kw))
    assert second[0]["op"] == "a"


def test_adapter_path_overrides_the_root(tmp_path, cache):
    p = tmp_path / "elsewhere.jsonl"
    _write(p, [{"at": "1"}])
    ad = {"z": {"at": ["at"], "path": str(p)}}
    assert len(list(ledgerlink.read("z", adapters=ad, root="/nonexistent", cache=cache))) == 1


def test_root_comes_from_configure_then_env_then_cwd(ledgers, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    _write(ledgers / "z.jsonl", [{"at": "A"}])
    _write(other / "z.jsonl", [{"at": "B"}])
    monkeypatch.chdir(other)
    assert [e["at"] for e in ledgerlink.read("z", cache=False)] == ["B"]
    monkeypatch.setenv("LEDGERLINK_ROOT", str(ledgers))
    assert [e["at"] for e in ledgerlink.read("z", cache=False)] == ["A"]
    ledgerlink.configure(root=str(other))
    assert [e["at"] for e in ledgerlink.read("z", cache=False)] == ["B"]


def test_configure_installs_the_adapter_table(ledgers, cache):
    _write(ledgers / "z.jsonl", [{"at": "1", "o": "x"}])
    ledgerlink.configure(adapters={"z": {"at": ["at"], "op": ["o"]}}, root=str(ledgers))
    assert next(iter(ledgerlink.read("z", cache=cache)))["op"] == "x"


def test_default_cache_path(monkeypatch, tmp_path):
    monkeypatch.delenv("LEDGERLINK_CACHE")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert cache_mod.default_path() == str(tmp_path / "xdg" / "ledgerlink" / "ledgerlink.sqlite")
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert cache_mod.default_path() == str(
        tmp_path / "home" / ".cache" / "ledgerlink" / "ledgerlink.sqlite"
    )
    monkeypatch.setenv("LEDGERLINK_CACHE", str(tmp_path / "x.sqlite"))
    assert cache_mod.default_path() == str(tmp_path / "x.sqlite")


def test_the_default_cache_is_used_when_none_is_given(ledgers, tmp_path):
    _write(ledgers / "z.jsonl", [{"at": "1"}])
    assert len(list(ledgerlink.read("z", root=str(ledgers)))) == 1
    assert (tmp_path / "default-cache" / "l.sqlite").exists()
