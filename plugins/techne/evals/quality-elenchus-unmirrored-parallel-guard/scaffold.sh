#!/bin/bash
set -euo pipefail
git init -q -b main . && git config user.email t@t && git config user.name t
cat > loader.py <<'EOF_FILE'
import pathlib

ROOT = pathlib.Path("configs").resolve()


def load_local(name: str) -> str:
    """Read configs/<name>; a name that escapes configs/ is refused."""
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"{name} is outside configs/")
    return path.read_text()
EOF_FILE
cat > test_loader.py <<'EOF_FILE'
import pytest

import loader


def test_local_refuses_escape():
    with pytest.raises(ValueError):
        loader.load_local("../secrets.txt")
EOF_FILE
git add -A && git commit -qm base
git checkout -q -b feature
cat > loader.py <<'EOF_FILE'
import pathlib
import urllib.parse

ROOT = pathlib.Path("configs").resolve()


def load_local(name: str) -> str:
    """Read configs/<name>; a name that escapes configs/ is refused."""
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError(f"{name} is outside configs/")
    return path.read_text()


def load_url_path(url: str) -> str:
    """Read the config a file:// style URL names, relative to configs/."""
    name = urllib.parse.unquote(urllib.parse.urlparse(url).path.lstrip("/"))
    return (ROOT / name).read_text()
EOF_FILE
cat > test_loader.py <<'EOF_FILE'
import pytest

import loader


def test_local_refuses_escape():
    with pytest.raises(ValueError):
        loader.load_local("../secrets.txt")


def test_url_path_reads(tmp_path, monkeypatch):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "a.toml").write_text("x = 1")
    monkeypatch.setattr(loader, "ROOT", tmp_path / "configs")
    assert loader.load_url_path("file:///a.toml") == "x = 1"
EOF_FILE
git add -A && git commit -qm "load configs from a URL path too"
