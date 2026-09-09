"""Shared test helpers."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal fake target repository."""
    repo_dir = tmp_path / "target-repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# target\n", encoding="utf-8")
    src = repo_dir / "src"
    src.mkdir()
    (src / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    return repo_dir
