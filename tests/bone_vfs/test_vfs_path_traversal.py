"""Bone VFS path-traversal fuzz corpus — the realpath-∈-scope containment in
`_resolve` is the LOAD-BEARING boundary between nOS-face users' real files.

Doctrine: pytest, prescriptive assertion messages. Incident this prevents: a
single traversal or symlink escape would let one face user read or write another
user's real tree. `test_vfs_containment.py` covers the core cases; this module
is the broadened adversarial matrix (backslash, URL-encoded, mixed, deeply
nested, absolute, symlink) so a future refactor of `_resolve` can't silently
narrow the gate. It ALSO pins that file CONTENT is stored/returned as inert
bytes — a `<script>` payload round-trips verbatim, never interpreted.

400 = "malformed request" (absolute path, invalid uid, bad leaf shape);
403 = "escapes user scope" (realpath containment). Either is a refusal — these
tests assert the request never reaches another user's data, and are lenient on
which of the two refusal codes a given input trips.
"""

from __future__ import annotations

import pytest

_REFUSED = {400, 403}


# ── Traversal on the READ side ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "../bob/secret.txt",
        "../../../../../../etc/passwd",     # deeply nested climb
        "documents/../../bob/secret.txt",   # mid-path climb
        "a/../../b",                        # nested up-and-over
        "/etc/passwd",                      # absolute POSIX
        "\\etc\\passwd",                    # backslash absolute (rejected by _resolve)
        "documents/./../../bob/secret.txt",  # with '.' noise
    ],
)
def test_read_traversal_refused(client, auth, path):
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": path}, headers=auth)
    assert r.status_code in _REFUSED, f"traversal {path!r} must be refused, got {r.status_code}"


@pytest.mark.parametrize(
    "path",
    [
        "../bob",
        "../../..",
        "documents/../../bob",
    ],
)
def test_list_traversal_refused(client, auth, path):
    r = client.get("/api/v1/vfs/list", params={"uid": "alice", "path": path}, headers=auth)
    assert r.status_code in _REFUSED, f"list traversal {path!r} must be refused, got {r.status_code}"


@pytest.mark.parametrize("path", ["..\\bob\\secret.txt", "..\\bob", "documents\\..\\..\\bob"])
def test_backslash_is_literal_on_posix_and_stays_contained(client, auth, path):
    # On the real host (macOS/Linux) a backslash is a LEGAL filename byte, not a
    # separator — so `..\bob\secret.txt` is a single literal name INSIDE alice's
    # root, never an escape. It must resolve contained (nonexistent → 404/empty)
    # and never surface bob's bytes. (The Windows-separator concern is handled by
    # the leaf sanitizer rejecting `\` on every write surface.)
    read = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": path}, headers=auth)
    assert read.status_code != 200 or "bob's private data" not in read.text, \
        f"backslash literal {path!r} must never leak bob's data"
    lst = client.get("/api/v1/vfs/list", params={"uid": "alice", "path": path}, headers=auth)
    if lst.status_code == 200:
        names = {e["name"] for e in lst.json()["entries"]}
        assert "secret.txt" not in names, f"backslash literal {path!r} must not list bob's tree"


def test_url_encoded_traversal_not_decoded_into_escape(client, auth):
    # %2e%2e%2f is the URL-encoded '../'. Query params ARE percent-decoded by the
    # transport, so this decodes to '../' and must be caught by containment;
    # if a future change stopped decoding, it becomes a literal (also contained).
    r = client.get(
        "/api/v1/vfs/read",
        params={"uid": "alice", "path": "%2e%2e%2fbob%2fsecret.txt"},
        headers=auth,
    )
    assert r.status_code in _REFUSED | {404}, "URL-encoded traversal must never reach bob's file"
    # The decisive assertion: alice never receives bob's bytes.
    if r.status_code == 200:
        pytest.fail("URL-encoded traversal leaked a 200 response")


# ── Traversal on the WRITE side ──────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    ["../bob/pwned.txt", "..\\bob\\pwned.txt", "../../../../tmp/pwned", "documents/../../bob/x"],
)
def test_write_traversal_refused(client, auth, path):
    r = client.post(
        "/api/v1/vfs/write",
        json={"uid": "alice", "path": path, "content": "pwned"},
        headers=auth,
    )
    assert r.status_code in _REFUSED, f"write traversal {path!r} must be refused, got {r.status_code}"


@pytest.mark.parametrize("uid", ["../bob", "..", ".", "a/b", ".hidden", ""])
def test_invalid_uid_refused(client, auth, uid):
    r = client.get("/api/v1/vfs/list", params={"uid": uid, "path": "documents"}, headers=auth)
    assert r.status_code in _REFUSED | {422}, f"invalid uid {uid!r} must be refused"


# ── Symlink escape: the realpath check is the whole point ────────────────────

def test_symlink_file_escape_refused(client, auth, vfs_env):
    _, users = vfs_env
    (users / "alice" / "escape").symlink_to(users / "bob")
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "escape/secret.txt"}, headers=auth)
    assert r.status_code == 403, "reading THROUGH a symlink out of scope must be 403"


def test_symlink_write_escape_refused(client, auth, vfs_env):
    _, users = vfs_env
    (users / "alice" / "escape").symlink_to(users / "bob")
    r = client.post(
        "/api/v1/vfs/write",
        json={"uid": "alice", "path": "escape/planted.txt", "content": "x"},
        headers=auth,
    )
    assert r.status_code == 403, "writing THROUGH a symlink out of scope must be 403"
    assert not (users / "bob" / "planted.txt").exists(), "no bytes may land in bob's tree"


def test_symlink_to_absolute_root_refused(client, auth, vfs_env, tmp_path):
    _, users = vfs_env
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("host secret", encoding="utf-8")
    (users / "alice" / "hostlink").symlink_to(tmp_path)
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "hostlink/outside-secret.txt"}, headers=auth)
    assert r.status_code == 403, "a symlink pointing outside the doctrine tree must be refused"


# ── Content is INERT: HTML/script round-trips as bytes, never executed ────────

def test_script_content_roundtrips_inert(client, auth):
    payload = '<script>alert(document.cookie)</script><img src=x onerror=alert(1)>'
    w = client.post(
        "/api/v1/vfs/write",
        json={"uid": "alice", "path": "documents/xss.html", "content": payload},
        headers=auth,
    )
    assert w.status_code == 200, "writing HTML content must succeed"
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "documents/xss.html"}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    # Returned verbatim as a JSON string value — inert, byte-for-byte identical.
    assert body["content"] == payload, "script content must round-trip unchanged (inert bytes)"
    assert body["encoding"] == "utf-8", "content is served as a UTF-8 JSON string, not rendered HTML"
    assert "application/json" in r.headers["content-type"], "response is JSON, never text/html"


def test_utf8_content_exact_roundtrip(client, auth):
    payload = "hÉllo 世界 🎉 — ünïcödé\nline2\t<b>not bold</b>"
    client.post(
        "/api/v1/vfs/write",
        json={"uid": "alice", "path": "documents/utf8.txt", "content": payload},
        headers=auth,
    )
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "documents/utf8.txt"}, headers=auth)
    assert r.json()["content"] == payload, "UTF-8 content must round-trip byte-exact"
