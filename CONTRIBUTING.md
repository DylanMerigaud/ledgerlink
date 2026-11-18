# Contributing

Bug reports with a few lines of the ledger (JSON Lines), the adapter you passed and the
envelope you expected are the most useful thing.

Changes are made here. A change is released as a new version, and the projects that use
ledgerlink bump their pin.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check . && mypy ledgerlink
```

## Rules

- The package imports the standard library only. No runtime dependency.
- Python 3.9 compatible.
- The envelope keys (`ENVELOPE_KEYS`) are a contract: consumers depend on them.
- A change to what a row becomes bumps `ENVELOPE_VERSION` so caches rebuild.
- A change to the envelope or the grammar comes with a test.
