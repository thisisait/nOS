"""Bone VFS filename hardening — the leaf-name sanitizer (fsnames.sanitize_leaf)
is the defense-in-depth layer that stops malformed/spoofing/reserved filenames
from ever landing on disk, on the axis `_resolve`'s realpath check does NOT cover.

Doctrine: pytest, prescriptive assertion messages, one incident per module. The
incident this prevents: the operator requirement "bulletproof against XSS,
malformed filenames, hard UTF-8 everywhere" — before this, `/write`/`/upload`
took a leaf with only `os.path.basename` + realpath containment, so a Windows
reserved name (`CON`), a BiDi RTL-override spoof (`invoice<U+202E>gpj.exe`), a
zero-width homoglyph, a control char, or a trailing-dot/space Win32 alias landed
verbatim and rendered ambiguously (or dangerously) in the face browser.

Most coverage is UNIT (no server needed) against `sanitize_leaf`; a thin slice
of route-level tests proves the 400 is actually wired into `/write` + `/upload`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BONE_DIR = ROOT / "files" / "anatomy" / "bone"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


fsnames = _load("bone_fsnames_under_test", BONE_DIR / "fsnames.py")
sanitize_leaf = fsnames.sanitize_leaf
sanitize_relpath = fsnames.sanitize_relpath
LeafNameError = fsnames.LeafNameError


# ── Accept side: valid names round-trip unchanged (or NFC-normalized) ─────────

@pytest.mark.parametrize(
    "name",
    [
        "hello.txt",
        "note.md",
        "My Document 2026.pdf",
        "report-final_v2.docx",
        "résumé.txt",          # accented latin (already NFC)
        "日本語.txt",            # CJK multibyte
        "Ελληνικά.txt",         # Greek
        "emoji-🎉.png",          # astral-plane codepoint
        "a" * 250 + ".txt",     # long but under the 255-byte cap
    ],
)
def test_valid_names_accepted(name):
    out = sanitize_leaf(name)
    assert isinstance(out, str) and out != "", f"expected {name!r} accepted, got {out!r}"


def test_nfc_normalization_collapses_nfd():
    # 'é' spelled NFD (e + combining acute) must normalize to the NFC form so
    # two spellings of the same visual name are one on-disk identity.
    nfd = "café.txt"          # 'café' as e + U+0301
    nfc = "café.txt"           # 'café' as single U+00E9
    assert sanitize_leaf(nfd) == nfc, "sanitize_leaf must NFC-normalize NFD input"
    assert sanitize_leaf(nfd) == sanitize_leaf(nfc), "NFD and NFC spellings must converge"


# ── Reject side: the malformed matrix ────────────────────────────────────────

@pytest.mark.parametrize("name", ["", ".", ".."])
def test_empty_and_dot_names_rejected(name):
    with pytest.raises(LeafNameError):
        sanitize_leaf(name)


@pytest.mark.parametrize("name", ["a/b", "a\\b", "/etc/passwd", "..\\x", "sub/leaf.txt"])
def test_path_separators_rejected(name):
    with pytest.raises(LeafNameError):
        sanitize_leaf(name)


@pytest.mark.parametrize(
    "name",
    [
        "a\x00b.txt",   # NUL
        "a\x01b.txt",   # C0 control
        "tab\tname",    # tab is C0
        "line\nname",   # newline is C0
        "a\x7fb",       # DEL
        "a\x85b",       # C1 (NEL)
    ],
)
def test_control_chars_rejected(name):
    with pytest.raises(LeafNameError):
        sanitize_leaf(name)


@pytest.mark.parametrize(
    "cp",
    [0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # BiDi embedding/override
     0x2066, 0x2067, 0x2068, 0x2069,          # BiDi isolates
     0x200B, 0x200C, 0x200D, 0x200E, 0x200F,  # zero-width + LRM/RLM
     0xFEFF],                                  # BOM / zero-width no-break
)
def test_bidi_and_zero_width_chars_rejected(cp):
    # The classic RTL-override attack: "invoice‮gpj.exe" renders as
    # "invoiceexe.jpg" but IS an .exe. Refuse the formatting char anywhere.
    name = f"file{chr(cp)}name.txt"
    with pytest.raises(LeafNameError):
        sanitize_leaf(name)


@pytest.mark.parametrize(
    "name",
    ["CON", "con", "Con", "PRN", "AUX", "NUL", "COM1", "com9", "LPT1", "lpt9",
     "con.txt", "NUL.tar.gz", "com1.log", "aux.backup"],
)
def test_windows_reserved_names_rejected(name):
    with pytest.raises(LeafNameError):
        sanitize_leaf(name)


def test_non_reserved_lookalikes_accepted():
    # Only the exact device stems are reserved — near-misses must pass.
    for ok in ("CONS", "com0", "com10", "lpt0", "console.txt", "printer.txt"):
        assert sanitize_leaf(ok) == ok, f"{ok!r} is not a reserved name and must be accepted"


@pytest.mark.parametrize("name", ["foo.", "foo ", "foo...", "bar   ", "baz. "])
def test_trailing_dot_or_space_rejected(name):
    with pytest.raises(LeafNameError):
        sanitize_leaf(name)


@pytest.mark.parametrize("name", [".hidden", ".face", ".git", ".env"])
def test_leading_dot_rejected_by_default(name):
    with pytest.raises(LeafNameError):
        sanitize_leaf(name)


def test_leading_dot_allowed_when_opted_in():
    # The routers can opt in for the few internal dot-names they legitimately
    # create; the user-facing default stays strict.
    assert sanitize_leaf(".face", allow_leading_dot=True) == ".face"


def test_overlong_name_rejected():
    # 256 ASCII bytes > the 255-byte NAME_MAX cap.
    with pytest.raises(LeafNameError):
        sanitize_leaf("a" * 256)


def test_overlong_multibyte_measured_in_bytes():
    # 200 'あ' = 600 UTF-8 bytes — over the cap even though only 200 codepoints.
    with pytest.raises(LeafNameError):
        sanitize_leaf("あ" * 200)


def test_unpaired_surrogate_rejected():
    with pytest.raises(LeafNameError):
        sanitize_leaf("bad\ud800name.txt")


# ── sanitize_relpath: per-segment validation ─────────────────────────────────

def test_relpath_validates_each_segment():
    assert sanitize_relpath("documents/reports/q3.pdf") == "documents/reports/q3.pdf"


@pytest.mark.parametrize("rel", ["a/../b", "documents/CON", "docs/bad\x00seg", "a/./b", ""])
def test_relpath_rejects_bad_segment(rel):
    with pytest.raises(LeafNameError):
        sanitize_relpath(rel)


def test_relpath_normalizes_backslash_and_dupe_slashes():
    assert sanitize_relpath("documents\\notes//a.txt") == "documents/notes/a.txt"


# ── Route-level: the 400 is actually wired into the write surfaces ───────────

@pytest.mark.parametrize(
    "leaf",
    ["CON", "bad\x00.txt", "file‮name.exe", "trailing.", ".hidden", "a" * 300],
)
def test_write_route_rejects_bad_leaf_400(client, auth, leaf):
    r = client.post(
        "/api/v1/vfs/write",
        json={"uid": "alice", "path": f"documents/{leaf}", "content": "x"},
        headers=auth,
    )
    assert r.status_code == 400, f"expected 400 for leaf {leaf!r}, got {r.status_code}"
    assert "invalid filename" in r.json()["detail"], "400 detail must name the reason"


def test_write_route_accepts_valid_unicode_leaf(client, auth):
    r = client.post(
        "/api/v1/vfs/write",
        json={"uid": "alice", "path": "documents/résumé-2026.txt", "content": "ok"},
        headers=auth,
    )
    assert r.status_code == 200, "a valid NFC unicode filename must be accepted"


def test_mkdir_route_rejects_reserved_leaf(client, auth):
    r = client.post("/api/v1/vfs/mkdir", json={"uid": "alice", "path": "NUL"}, headers=auth)
    assert r.status_code == 400, "mkdir must refuse a Windows reserved device name"


def test_move_and_copy_reject_bad_dst_leaf(client, auth):
    mv = client.post(
        "/api/v1/vfs/move",
        json={"uid": "alice", "src": "documents/hello.txt", "dst": "documents/CON"},
        headers=auth,
    )
    assert mv.status_code == 400, "move must sanitize the destination leaf"
    cp = client.post(
        "/api/v1/vfs/copy",
        json={"uid": "alice", "src": "documents/hello.txt", "dst": "documents/bad​.txt"},
        headers=auth,
    )
    assert cp.status_code == 400, "copy must sanitize the destination leaf"


def test_upload_route_rejects_bad_filename(client, auth):
    r = client.post(
        "/api/v1/vfs/upload",
        params={"uid": "alice", "path": "documents", "filename": "CON"},
        content=b"payload",
        headers=auth,
    )
    assert r.status_code == 400, "upload must sanitize the supplied filename"


def test_upload_route_accepts_valid_filename(client, auth):
    r = client.post(
        "/api/v1/vfs/upload",
        params={"uid": "alice", "path": "documents", "filename": "photo.png"},
        content=b"\x89PNG\r\n",
        headers=auth,
    )
    assert r.status_code == 200, "a valid upload filename must be accepted"
