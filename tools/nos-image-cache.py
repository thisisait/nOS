#!/usr/bin/env python3
"""A verified local cache of container images, so a rebuild does not re-pull.

A leave (remove=all includes deep) prunes every image; the rebuild after it
pulled 68 images / 66.6 GB again, 55 of them from Docker Hub, the registry
that rate-limits by IP (measured 2026-09-30). This keeps one `docker save`
tar per image under <root>/images/ with a lock file naming the image id,
registry digest and the tar's sha256. `load` only feeds docker a tar whose
checksum still matches the lock; anything else is refused and left for
compose to pull.

  tools/nos-image-cache.py --root DIR seed      # save every tagged local image not yet cached
  tools/nos-image-cache.py --root DIR load      # load cached images the daemon lacks
  tools/nos-image-cache.py --root DIR verify    # re-hash every tar against the lock
  tools/nos-image-cache.py --root DIR status
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DOCKER = os.environ.get("NOS_DOCKER_BIN", "docker")


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([DOCKER, *args], capture_output=True, text=True, check=check)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _lock_path(root: Path) -> Path:
    return root / "images" / "images.lock.json"


def _read_lock(root: Path) -> dict:
    p = _lock_path(root)
    return json.loads(p.read_text()) if p.exists() else {"version": 1, "images": {}}


def _write_lock(root: Path, lock: dict) -> None:
    p = _lock_path(root)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    tmp.replace(p)


def _inspect(ref: str) -> tuple[str, list[str]] | None:
    r = _docker("image", "inspect", "--format", "{{.Id}}|{{json .RepoDigests}}", ref, check=False)
    if r.returncode != 0:
        return None
    img_id, digests = r.stdout.strip().split("|", 1)
    return img_id, json.loads(digests or "[]")


def _local_refs() -> list[str]:
    """Tagged images by tag; an image kept only by digest (a compose ref pinned
    `name:tag@sha256:…` lands untagged) by its repo digest — skipping those
    left mcp-grafana and apex's nginx out of the first seed (2026-09-30)."""
    refs = set()
    for line in _docker("image", "ls", "--format", "{{.ID}}|{{.Repository}}|{{.Tag}}").stdout.splitlines():
        img_id, repo, tag = line.split("|")
        if repo != "<none>" and tag != "<none>":
            refs.add(f"{repo}:{tag}")
            continue
        info = _inspect(img_id)
        if info and info[1]:
            refs.add(info[1][0])
    return sorted(refs)


def _tar_name(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", ref) + ".tar"


def seed(root: Path) -> int:
    (root / "images").mkdir(parents=True, exist_ok=True)
    lock = _read_lock(root)
    saved = kept = 0
    for ref in _local_refs():
        info = _inspect(ref)
        if info is None:
            continue
        img_id, digests = info
        entry = lock["images"].get(ref)
        tar = root / "images" / _tar_name(ref)
        if entry and entry["id"] == img_id and tar.exists() and tar.stat().st_size == entry["bytes"]:
            kept += 1
            continue
        part = tar.with_suffix(".tar.part")
        _docker("save", "-o", str(part), ref)
        part.replace(tar)
        lock["images"][ref] = {
            "id": img_id, "digests": digests, "file": tar.name,
            "sha256": _sha256(tar), "bytes": tar.stat().st_size,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _write_lock(root, lock)          # after EVERY image: an interrupted seed keeps its progress
        saved += 1
        print(f"saved {ref}")
    print(f"seed: {saved} saved, {kept} already cached, {len(lock['images'])} in lock")
    return 0


def load(root: Path) -> int:
    lock = _read_lock(root)
    loaded = present = 0
    refused: list[str] = []
    for ref, e in sorted(lock["images"].items()):
        info = _inspect(ref)
        if info and info[0] == e["id"]:
            present += 1
            continue
        tar = root / "images" / e["file"]
        if not tar.exists() or _sha256(tar) != e["sha256"]:
            refused.append(ref)
            print(f"REFUSED {ref}: tar missing or checksum differs from the lock", file=sys.stderr)
            continue
        _docker("load", "-i", str(tar))
        after = _inspect(ref)
        if not after or after[0] != e["id"]:
            refused.append(ref)
            print(f"REFUSED {ref}: loaded, but the daemon reports a different image id", file=sys.stderr)
            continue
        loaded += 1
        print(f"loaded {ref}")
    print(f"load: {loaded} loaded, {present} already present, {len(refused)} refused")
    return 1 if refused else 0


def verify(root: Path) -> int:
    lock = _read_lock(root)
    bad = [ref for ref, e in lock["images"].items()
           if not (root / "images" / e["file"]).exists() or _sha256(root / "images" / e["file"]) != e["sha256"]]
    for ref in bad:
        print(f"BAD {ref}")
    print(f"verify: {len(lock['images']) - len(bad)} ok, {len(bad)} bad")
    return 1 if bad else 0


def status(root: Path) -> int:
    lock = _read_lock(root)
    total = sum(e["bytes"] for e in lock["images"].values())
    print(f"{len(lock['images'])} images, {total / 1e9:.1f} GB, lock {_lock_path(root)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("verb", choices=["seed", "load", "verify", "status"])
    a = ap.parse_args(argv)
    return {"seed": seed, "load": load, "verify": verify, "status": status}[a.verb](a.root)


if __name__ == "__main__":
    sys.exit(main())
