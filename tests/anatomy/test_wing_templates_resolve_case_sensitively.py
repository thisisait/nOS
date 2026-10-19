"""Wing finds its templates on a case-sensitive filesystem.

The templates live in files/anatomy/wing/app/Templates/ (capital T). Nette's
default lookup is app/templates/: the same directory on a case-insensitive
macOS volume, a missing one on Linux — where every HTML page 404'd while the
JSON API answered (spark1, 2026-10-19). BasePresenter names the directory.
"""
from __future__ import annotations

import pathlib
import re

WING = pathlib.Path(__file__).resolve().parents[2] / "files" / "anatomy" / "wing" / "app"


def test_the_directory_is_spelt_as_the_presenter_names_it():
    base = (WING / "Presenters" / "BasePresenter.php").read_text(encoding="utf-8")
    for fn in ("formatTemplateFiles", "formatLayoutTemplateFiles"):
        body = re.search(rf"function {fn}\(\): array\s*\{{(.*?)\n\t\}}", base, re.S)
        assert body, f"BasePresenter does not override {fn} — Nette would look in app/templates/"
        assert "'/Templates'" in body.group(1), f"{fn} must name app/Templates exactly"
    assert (WING / "Templates").is_dir() and not (WING / "templates").exists()
    assert (WING / "Templates" / "@layout.latte").is_file()
