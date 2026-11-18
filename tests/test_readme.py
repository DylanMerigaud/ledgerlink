"""Every python block of the README runs as written."""

import re
from pathlib import Path

import pytest

README = Path(__file__).resolve().parent.parent / "README.md"
BLOCKS = re.findall(r"```python\n(.*?)```", README.read_text(encoding="utf-8"), re.S)


def test_the_readme_has_python_blocks():
    assert len(BLOCKS) >= 2


@pytest.mark.parametrize("index", range(len(BLOCKS)))
def test_readme_block_runs(index, capsys):
    exec(compile(BLOCKS[index], f"README block {index}", "exec"), {"__name__": "__readme__"})
    assert capsys.readouterr().out


def test_examples_run(tmp_path, monkeypatch):
    import runpy

    monkeypatch.chdir(tmp_path)
    for path in sorted((README.parent / "examples").glob("*.py")):
        runpy.run_path(str(path), run_name="__main__")
