"""The repository is GPL-3.0-only (it ships overrides derived from bidspm, which is GPL-3.0 without 'or later')."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_licence_file_is_gpl3():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text


def test_readme_names_the_licence_and_not_mit():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "GPL-3.0" in readme and "MIT License" not in readme
