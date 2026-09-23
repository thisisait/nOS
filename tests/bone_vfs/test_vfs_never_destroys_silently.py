"""No VFS write may destroy a document the caller did not name.

FOUND 2026-09-23 while building the Files explorer. `/copy` had always refused
a clash (409), while `/move` used `shutil.move` and `/upload` used
`open("wb")` — both replace. Moving `invoice.jpg` into a folder that already
held one lost a document with no error, and a phone hands every camera shot
over as `image.jpg`, so the second upload of the day overwrote the first.

The explorer guards both client-side, but a client guard is TOCTOU and covers
exactly one caller. The refusal belongs at the door, and replacing has to be a
deliberate act: `overwrite: true` on /move, `?overwrite=true` on /upload.
"""

from __future__ import annotations


def _write(client, auth, path: str, text: str):
    r = client.post("/api/v1/vfs/write",
                    json={"uid": "alice", "path": path, "content": text}, headers=auth)
    assert r.status_code == 200, r.text


def _read(client, auth, path: str) -> str:
    r = client.get("/api/v1/vfs/read", params={"uid": "alice", "path": path}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["content"]


def test_move_refuses_to_replace(client, auth):
    """The defect, as the thing that must stay false."""
    _write(client, auth, "documents/a.txt", "KEEP")
    _write(client, auth, "documents/b.txt", "OTHER")
    r = client.post("/api/v1/vfs/move",
                    json={"uid": "alice", "src": "documents/b.txt", "dst": "documents/a.txt"},
                    headers=auth)
    assert r.status_code == 409, r.text
    assert _read(client, auth, "documents/a.txt") == "KEEP"


def test_move_replaces_when_asked(client, auth):
    _write(client, auth, "documents/a.txt", "KEEP")
    _write(client, auth, "documents/b.txt", "OTHER")
    r = client.post("/api/v1/vfs/move",
                    json={"uid": "alice", "src": "documents/b.txt", "dst": "documents/a.txt",
                          "overwrite": True}, headers=auth)
    assert r.status_code == 200, r.text
    assert _read(client, auth, "documents/a.txt") == "OTHER"


def test_move_to_a_free_name_still_works(client, auth):
    """A detector that cannot report green is no detector."""
    _write(client, auth, "documents/a.txt", "KEEP")
    r = client.post("/api/v1/vfs/move",
                    json={"uid": "alice", "src": "documents/a.txt", "dst": "documents/c.txt"},
                    headers=auth)
    assert r.status_code == 200, r.text
    assert _read(client, auth, "documents/c.txt") == "KEEP"


def test_upload_refuses_to_replace(client, auth):
    _write(client, auth, "documents/image.jpg", "YESTERDAY")
    r = client.post("/api/v1/vfs/upload",
                    params={"uid": "alice", "path": "documents", "filename": "image.jpg"},
                    content=b"TODAY", headers=auth)
    assert r.status_code == 409, r.text
    assert _read(client, auth, "documents/image.jpg") == "YESTERDAY"


def test_upload_replaces_when_asked(client, auth):
    _write(client, auth, "documents/image.jpg", "YESTERDAY")
    r = client.post("/api/v1/vfs/upload",
                    params={"uid": "alice", "path": "documents", "filename": "image.jpg",
                            "overwrite": "true"},
                    content=b"TODAY", headers=auth)
    assert r.status_code == 200, r.text
    assert _read(client, auth, "documents/image.jpg") == "TODAY"


def test_a_first_upload_still_lands(client, auth):
    r = client.post("/api/v1/vfs/upload",
                    params={"uid": "alice", "path": "documents", "filename": "new.txt"},
                    content=b"HELLO", headers=auth)
    assert r.status_code == 200, r.text
    assert _read(client, auth, "documents/new.txt") == "HELLO"
