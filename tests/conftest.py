import pytest

from ledgerlink import reader, refs
from ledgerlink.cache import Cache


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("LEDGERLINK_CACHE", str(tmp_path / "default-cache" / "l.sqlite"))
    monkeypatch.delenv("LEDGERLINK_ROOT", raising=False)
    monkeypatch.delenv("LEDGERLINK_ACTOR", raising=False)
    saved = dict(reader._config)
    saved_stores = dict(refs._stores)
    reader._config.update(
        {"adapters": {}, "root": None, "actor_env": None, "clean": None, "validate": None}
    )
    refs.unregister()
    yield
    reader._config.update(saved)
    refs._stores.clear()
    refs._stores.update(saved_stores)
    refs.unregister()


@pytest.fixture
def ledgers(tmp_path):
    d = tmp_path / "ledgers"
    d.mkdir()
    return d


@pytest.fixture
def cache(tmp_path):
    c = Cache(str(tmp_path / "cache" / "l.sqlite"))
    yield c
    c.close()
