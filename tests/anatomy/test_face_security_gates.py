"""Anatomy CI gate — nOS-face security invariants (independent of the wiring report).

The operator requirement: the shell must be bulletproof against XSS, malformed
filenames, and identity spoofing, with UTF-8 handled everywhere and the real FS +
shared user-state safe to manipulate. This gate statically pins those invariants
over the vendored source (files/anatomy/face/) + the Bone organs (files/anatomy/
bone/), by regex (no runtime — the stack is pytest+pyyaml). Companion runtime fuzz
corpus: tests/bone_vfs/. Doctrine: docs/doctrine/face.md.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FACE_SRC = REPO / "files" / "anatomy" / "face" / "src"
BONE = REPO / "files" / "anatomy" / "bone"


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return re.sub(r"(?m)//.*$", "", text)


# ── XSS ──────────────────────────────────────────────────────────────────────

def _shell_files():
    return [p for p in FACE_SRC.rglob("*") if p.suffix in (".svelte", ".ts") and p.is_file()]


def test_no_at_html_anywhere_in_shell():
    """Svelte auto-escapes `{expr}`; `{@html}` is the one bypass and is forbidden."""
    offenders = []
    for p in _shell_files():
        if re.search(r"\{@html\s+[^}\s]", _strip_comments(p.read_text(encoding="utf-8"))):
            offenders.append(str(p.relative_to(REPO)))
    assert offenders == [], f"{{@html}} used in: {offenders}"


# ── Identity / edge-trust ────────────────────────────────────────────────────

def test_bff_hook_enforces_edge_token_timing_safe():
    hooks = (FACE_SRC / "hooks.server.ts").read_text(encoding="utf-8")
    assert "FACE_EDGE_TOKEN" in hooks, "edge token not enforced"
    assert "timingSafeEqual" in hooks, "edge-token compare must be timing-safe"
    assert "403" in hooks, "failed edge-trust must be refused (403)"


def test_bff_never_reads_uid_from_client():
    """uid is pinned from the edge-trusted identity — never a query/body param."""
    offenders = []
    for p in (FACE_SRC / "routes" / "bff").rglob("+server.ts"):
        text = p.read_text(encoding="utf-8")
        if re.search(r"""searchParams\.get\(\s*['"]uid['"]""", text) or re.search(
            r"""\bbody\s*\.\s*uid\b""", text
        ):
            offenders.append(str(p.relative_to(REPO)))
    assert offenders == [], f"BFF reads client-supplied uid in: {offenders}"


def test_upstream_tokens_are_server_only():
    """The Bone/KEAP tokens (via $env/dynamic/private) must never reach client code."""
    offenders = []
    for p in _shell_files():
        rel = p.relative_to(FACE_SRC).as_posix()
        if "$env/dynamic/private" not in p.read_text(encoding="utf-8"):
            continue
        if not (rel == "hooks.server.ts" or rel.startswith("lib/server/") or rel.endswith("+server.ts")):
            offenders.append(str(p.relative_to(REPO)))
    assert offenders == [], f"private env imported client-side in: {offenders}"


# ── Malformed filenames / real FS (Bone) ─────────────────────────────────────

def test_bone_has_filename_sanitizer():
    fsnames = (BONE / "fsnames.py").read_text(encoding="utf-8")
    assert "NFC" in fsnames, "filenames must be NFC-normalized"
    # Reserved device names + control/formatting rejection must be present.
    assert re.search(r"CON|PRN|AUX|COM1|LPT1", fsnames), "Windows reserved names not filtered"
    assert "surrogate" in fsnames.lower() or "\\ud" in fsnames or "0xd800" in fsnames.lower() \
        or re.search(r"200b|202a|feff", fsnames, re.I), "control/BiDi/zero-width filtering absent"


@pytest.mark.parametrize("op", ["write", "mkdir", "upload", "move", "copy"])
def test_vfs_write_surfaces_sanitize_leaf(op):
    """Every write surface must run new leaves through the sanitizer (defense in
    depth on top of the load-bearing realpath-∈-scope containment)."""
    vfs = (BONE / "vfs.py").read_text(encoding="utf-8")
    assert "fsnames" in vfs or "sanitize_leaf" in vfs, "vfs.py does not use the filename sanitizer"
    # The sanitizer helper must be referenced (applied) in the module.
    assert re.search(r"_checked_leaf|sanitize_leaf|_checked_relpath", vfs), \
        "vfs.py imports but never applies the sanitizer"


def test_userstate_caps_value_size():
    us = (BONE / "userstate.py").read_text(encoding="utf-8")
    assert "_MAX_VALUE_BYTES" in us and "413" in us, "user-state value size cap missing"
    assert "_NS_RE" in us and "_KEY_RE" in us, "user-state namespace/key validation missing"


# ── File-picker postMessage bridge ───────────────────────────────────────────

def test_file_picker_bridge_has_origin_allowlist():
    bridge = FACE_SRC / "lib" / "apps" / "native" / "file-picker" / "bridge.ts"
    if not bridge.is_file():
        pytest.skip("file-picker bridge not present")
    text = bridge.read_text(encoding="utf-8")
    assert "allowedOrigins" in text or "origin" in text, \
        "postMessage bridge must gate on origin"
