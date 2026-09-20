"""Invoice PDFs under nos_data_root tenants .../incoming/ ride the nightly dir tar.

Week-1 P3: KEAP's dump is keap.db only — it does not save PDFs. Originals live at

    {nos_data_root}/tenants/<t>/users/<uid>/inbox/accounting/<book_owner>/incoming/

Copy #1 (`backup.sh` `run_dirs`) tars each `backup_dirs_to_dump` path whole
(`tar -czvf - .`). There is no second restic path. A `--exclude` of `incoming/`
or a backup set that is only the KEAP sqlite dump would drop the PDFs.

Reader: this file greps the script + dump list. backup.sh logging OK is not evidence.

CI-safe: source scan. No Docker, no live host, no network.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKUP_SH = REPO / "roles" / "pazny.backup" / "files" / "backup.sh"
BACKUP_DEFAULTS = REPO / "roles" / "pazny.backup" / "defaults" / "main.yml"
PLAY_CONFIG = REPO / "default.config.yml"


def _code(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )


def _fn(name: str) -> str:
    body = BACKUP_SH.read_text(encoding="utf-8")
    start = body.index(f"{name}() {{")
    end = body.index("\n}\n", start)
    return body[start:end]


def _exclude_hits(text: str) -> list[str]:
    return [
        ln.strip()
        for ln in _code(text).splitlines()
        if re.search(r"--exclude", ln) and "incoming" in ln
    ]


def test_run_dirs_tars_the_whole_tree_and_does_not_exclude_incoming():
    """If incoming/ sits under a dumped nos_data_root path, it must ride along."""
    fn = _fn("run_dirs")
    assert "tar -czvf - ." in fn, (
        "run_dirs no longer tars the directory whole — incoming/ PDFs would "
        "need a dedicated source, which this estate does not add"
    )
    assert not _exclude_hits(fn), (
        "run_dirs excludes incoming/ — invoice PDFs would drop out of copy #1 "
        f"while keap-db still looks green: {_exclude_hits(fn)}"
    )
    assert not _exclude_hits(BACKUP_SH.read_text(encoding="utf-8")), (
        "backup.sh gained an --exclude of incoming/"
    )


def test_keap_dump_is_the_db_not_the_pdfs():
    """Week-1 P3: the cortex dump cannot stand in for filesystem originals."""
    fn = _code(_fn("run_keap_db"))
    assert "incoming" not in fn, (
        "run_keap_db started touching incoming/ — PDFs are not in keap.db; "
        "keep the dump as the sqlite store"
    )
    assert "keap-db.gz" in fn and "KEAP_DB" in fn
    assert ".pdf" not in fn.lower()


def test_nightly_set_is_not_only_the_keap_db():
    """Filesystem originals need a dir tar; keap-db.gz is not that tar."""
    main = _fn("main")
    assert "run_dirs" in main and "run_keap_db" in main
    for src in (BACKUP_DEFAULTS, PLAY_CONFIG):
        text = src.read_text(encoding="utf-8")
        start = text.index("backup_dirs_to_dump:")
        names = re.findall(r'\{ name: "([a-z0-9-]+)"', text[start:])
        assert names, f"{src} backup_dirs_to_dump parsed empty"
        assert "tenants" in names, (
            f"{src} dump list has no tenants entry — invoice incoming/ PDFs "
            f"are not under gitea/n8n: {names}"
        )
        assert not _exclude_hits(text), (
            f"{src} excludes incoming/ from the dump list: {_exclude_hits(text)}"
        )
