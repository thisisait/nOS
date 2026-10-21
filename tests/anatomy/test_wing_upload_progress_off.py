"""Anatomy gate — Wing's PHP runs with session upload progress OFF.

THE SYMPTOM (2026-10-21, spark1). Public reports of a heap use-after-free in
PHP's ``session.upload_progress`` handler (CVE-2026-109618/-109619, claimed
code execution) found Wing on PHP 8.5.8 with the stock
``session.upload_progress.enabled = 1``: no php.ini, nothing in nOS set it.
Wing listens on 127.0.0.1 and the docker bridge, so every local user and every
container could POST multipart to it, and Wing runs as the operator.

THE FIX. Wing never reports upload progress, so the FrankenPHP global block
sets ``php_ini session.upload_progress.enabled 0``. This closes the handler
path only; the multipart-parser path closes with a patched PHP (frankenphp_version).

CEILING. Reads the template, not the running process; the effect is
``ini_get('session.upload_progress.enabled')`` served by the live Wing.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CADDY = REPO / "roles" / "pazny.wing" / "templates" / "wing.Caddyfile.j2"


def _frankenphp_block() -> str:
    text = CADDY.read_text(encoding="utf-8")
    m = re.search(r"^\s*frankenphp\s*\{(.*?)^\s*\}", text, re.S | re.M)
    assert m, f"no global frankenphp {{ }} block in {CADDY.name}"
    return m.group(1)


def test_upload_progress_is_off_in_the_frankenphp_block():
    lines = [ln.split("#", 1)[0].split() for ln in _frankenphp_block().splitlines()]
    assert ["php_ini", "session.upload_progress.enabled", "0"] in lines, \
        "Wing's PHP keeps the stock session.upload_progress.enabled = On"
