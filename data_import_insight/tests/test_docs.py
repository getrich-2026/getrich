from __future__ import annotations

from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]


def test_readme_uses_committed_example_config_and_global_config_order() -> None:
    readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8")

    assert "config/defaults.example.toml" in readme
    assert "cp config/defaults.toml" not in readme
    assert "init-schema --config" not in readme
    assert "load-metadata --config" not in readme
    assert "import-bars --asset" in readme


def test_example_config_is_committed() -> None:
    assert (PROJECT_DIR / "config" / "defaults.example.toml").exists()
