"""Bone VFS — the load-bearing security gate: realpath-∈-scope containment,
cross-user isolation, and the static-bearer token. If any of these regress, one
nOS-face user could read or write another user's real files."""

from __future__ import annotations


# ── Happy path ───────────────────────────────────────────────────────────────

def test_list_own_documents(client, auth):
    r = client.get("/api/v1/vfs/list", params={"uid": "alice", "path": "documents"}, headers=auth)
    assert r.status_code == 200
    names = {e["name"] for e in r.json()["entries"]}
    assert "hello.txt" in names


def test_read_own_file(client, auth):
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "documents/hello.txt"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["content"] == "hi from alice"


def test_missing_dir_lists_empty(client, auth):
    r = client.get("/api/v1/vfs/list", params={"uid": "alice", "path": "does-not-exist"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["entries"] == []


def test_write_then_read(client, auth):
    w = client.post("/api/v1/vfs/write", json={"uid": "alice", "path": "documents/note.md", "content": "# hi"}, headers=auth)
    assert w.status_code == 200
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "documents/note.md"}, headers=auth)
    assert r.json()["content"] == "# hi"


def test_mkdir_and_move(client, auth):
    assert client.post("/api/v1/vfs/mkdir", json={"uid": "alice", "path": "projects"}, headers=auth).status_code == 200
    mv = client.post("/api/v1/vfs/move", json={"uid": "alice", "src": "documents/hello.txt", "dst": "projects/hello.txt"}, headers=auth)
    assert mv.status_code == 200
    assert client.get("/api/v1/vfs/list", params={"uid": "alice", "path": "projects"}, headers=auth).json()["entries"]


def test_copy_file(client, auth):
    r = client.post("/api/v1/vfs/copy", json={"uid": "alice", "src": "documents/hello.txt", "dst": "documents/hello-copy.txt"}, headers=auth)
    assert r.status_code == 200
    names = {e["name"] for e in client.get("/api/v1/vfs/list", params={"uid": "alice", "path": "documents"}, headers=auth).json()["entries"]}
    assert {"hello.txt", "hello-copy.txt"} <= names


def test_copy_conflict_409(client, auth):
    r = client.post("/api/v1/vfs/copy", json={"uid": "alice", "src": "documents/hello.txt", "dst": "documents/hello.txt"}, headers=auth)
    assert r.status_code == 409


def test_delete_file(client, auth):
    assert client.post("/api/v1/vfs/delete", json={"uid": "alice", "path": "documents/hello.txt"}, headers=auth).status_code == 200
    assert client.get("/api/v1/vfs/stat", params={"uid": "alice", "path": "documents/hello.txt"}, headers=auth).status_code == 404


def test_copy_escape_refused(client, auth):
    assert client.post("/api/v1/vfs/copy", json={"uid": "alice", "src": "../bob/secret.txt", "dst": "documents/x"}, headers=auth).status_code == 403
    assert client.post("/api/v1/vfs/copy", json={"uid": "alice", "src": "documents/hello.txt", "dst": "../bob/pwned"}, headers=auth).status_code == 403


def test_delete_escape_refused(client, auth):
    assert client.post("/api/v1/vfs/delete", json={"uid": "alice", "path": "../bob/secret.txt"}, headers=auth).status_code == 403


def test_delete_user_root_refused(client, auth):
    assert client.post("/api/v1/vfs/delete", json={"uid": "alice", "path": ""}, headers=auth).status_code == 400


# ── Containment: the security core ───────────────────────────────────────────

def test_dotdot_escape_refused(client, auth):
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "../bob/secret.txt"}, headers=auth)
    assert r.status_code == 403


def test_cross_user_list_refused(client, auth):
    # alice trying to reach bob's tree by climbing out of her root.
    r = client.get("/api/v1/vfs/list", params={"uid": "alice", "path": "../bob"}, headers=auth)
    assert r.status_code == 403


def test_absolute_path_refused(client, auth):
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "/etc/passwd"}, headers=auth)
    assert r.status_code == 400


def test_deep_traversal_refused(client, auth):
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "../../../../../../etc/passwd"}, headers=auth)
    assert r.status_code == 403


def test_symlink_escape_refused(client, auth, vfs_env):
    _, users = vfs_env
    # alice plants a symlink to bob's dir; resolving through it must be refused.
    (users / "alice" / "escape").symlink_to(users / "bob")
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": "escape/secret.txt"}, headers=auth)
    assert r.status_code == 403


def test_write_escape_refused(client, auth):
    r = client.post("/api/v1/vfs/write", json={"uid": "alice", "path": "../bob/pwned.txt", "content": "x"}, headers=auth)
    assert r.status_code == 403


def test_uid_with_slash_refused(client, auth):
    r = client.get("/api/v1/vfs/list", params={"uid": "../bob", "path": "documents"}, headers=auth)
    assert r.status_code == 400


# ── Token gate ───────────────────────────────────────────────────────────────

def test_no_token_401(client):
    r = client.get("/api/v1/vfs/list", params={"uid": "alice", "path": "documents"})
    assert r.status_code == 401


def test_wrong_token_403(client):
    r = client.get("/api/v1/vfs/list", params={"uid": "alice", "path": "documents"}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 403
