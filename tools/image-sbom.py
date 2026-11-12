#!/usr/bin/env python3
"""Every running image scanned to its packages: syft builds the SBOM, grype matches it (row one-node-and-image-sbom).

WHY. advisory-status matches the PINS; a base image's own packages (alpine's openssl, npm's
brace-expansion) are inside no pin and passed unseen. This saves each running image to a tar and runs
the pinned scanners (syft_image / grype_image, default.config.yml, tag AND digest) as containers.

TRUST. No docker.sock in a scanner. Both scans run --network none, --cap-drop ALL, as your uid; the
image tar and the SBOM are mounted :ro. The grype DB (~/.nos/sbom/grype-db, 0700) is grype's only rw
mount, and only `grype db update` has network (a GET to Anchore's DB listing).

A limb, not a reader: it writes ~/.nos/sbom/last.json (0600) and the SBOMs. Exit, like advisory-patrol:
  0  every image scanned, no critical match with a fix
  10 a critical match with a fix available
  11 something UNKNOWN (an unsaved or unscanned image, no usable DB, a DB over 5 days old, a pin
     without a digest): NOTHING FOUND IS NOT CLEAN

Usage:
    tools/image-sbom.py [--json] [--image REF] [--no-db-update] [--selftest]
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nos_identity as ni  # noqa: E402

_spec = importlib.util.spec_from_file_location("container_status", Path(__file__).with_name("container-status.py"))
_cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cs)

ROOT = Path.home() / ".nos" / "sbom"
STALE = dt.timedelta(days=5)
PINNED = re.compile(r"^[\w./:-]+@sha256:[0-9a-f]{64}$")
STEP_S = 900  # one docker save or scan; a multi-GB image saves in minutes
QUIET = ["-e", "SYFT_CHECK_FOR_APP_UPDATE=false", "-e", "GRYPE_CHECK_FOR_APP_UPDATE=false"]


def docker_bin() -> str | None:
    """PATH first, then the usual installs (a launchd job's PATH is short)."""
    found = shutil.which("docker")
    return found or next((p for p in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker", "/usr/bin/docker")
                          if os.access(p, os.X_OK)), None)


def run(argv: list[str], timeout: int = STEP_S) -> tuple[int, str, str]:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return r.returncode, r.stdout, r.stderr


def jail(docker: str, *, network: bool = False) -> list[str]:
    """The scanner container's flags: never the socket, no caps, your uid."""
    return [docker, "run", "--rm", *([] if network else ["--network", "none"]), "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}", *QUIET]


def running_images(containers: list[dict]) -> list[dict]:
    """One entry per image id a running container uses, with the names it runs as."""
    by_id: dict[str, dict] = {}
    for c in containers:
        if not (c.get("State") or {}).get("Running") or not c.get("Image"):
            continue
        e = by_id.setdefault(c["Image"], {"id": c["Image"], "ref": (c.get("Config") or {}).get("Image") or c["Image"],
                                          "containers": []})
        e["containers"].append((c.get("Name") or "?").lstrip("/"))
    return sorted(by_id.values(), key=lambda e: e["ref"])


def db_state(status: dict | None, now: dt.datetime) -> dict:
    """grype `db status -o json` -> usable / stale. Unparseable is unusable, never fresh."""
    if not status or not status.get("valid"):
        return {"usable": False, "why": (status or {}).get("error") or "no grype DB status"}
    try:
        built = dt.datetime.fromisoformat(str(status.get("built", "")).replace("Z", "+00:00"))
    except ValueError:
        return {"usable": True, "stale": True, "why": "DB build date unreadable"}
    age = now - built
    return {"usable": True, "built": status["built"], "schema": status.get("schemaVersion"),
            "stale": age > STALE, "age_days": round(age.total_seconds() / 86400, 1)}


def tally(grype: dict) -> dict:
    """Severity counts and the critical ids a fix exists for."""
    matches = grype.get("matches") or []
    sev = Counter(str((m.get("vulnerability") or {}).get("severity") or "Unknown") for m in matches)
    fixable = sorted({m["vulnerability"].get("id", "?") for m in matches
                      if m.get("vulnerability", {}).get("severity") == "Critical"
                      and (m["vulnerability"].get("fix") or {}).get("state") == "fixed"})
    return {"severity": dict(sorted(sev.items())), "critical_fixable": fixable}


def verdict(rows: list[dict], db: dict, refused: str | None) -> tuple[str, int]:
    if refused or not db.get("usable") or db.get("stale") or any(r["state"] == "UNKNOWN" for r in rows):
        return "UNKNOWN", 11
    if any(r.get("critical_fixable") for r in rows):
        return "findings", 10
    return "ok", 0


def scan(docker: str, img: dict, syft: str, grype: str) -> dict:
    """save -> syft -> grype for one image; any step failing makes the image UNKNOWN."""
    row = {"ref": img["ref"], "id": img["id"], "containers": img["containers"]}
    key = img["id"].split(":")[-1][:12]
    work, sboms = ROOT / "work", ROOT / "sboms"
    tar, sbom = work / f"{key}.tar", sboms / f"{key}.syft.json"
    try:
        rc, _, err = run([docker, "save", "-o", str(tar), img["id"]])
        if rc:
            return {**row, "state": "UNKNOWN", "why": f"docker save: {err.strip()[-200:]}"}
        tar.chmod(0o600)
        rc, out, err = run([*jail(docker), "-e", "TMPDIR=/work", "-v", f"{tar}:/in.tar:ro", "-v", f"{work}:/work",
                            syft, "docker-archive:/in.tar", "-o", "syft-json", "-q"])
        if rc:
            return {**row, "state": "UNKNOWN", "why": f"syft: {err.strip()[-200:]}"}
        write(sbom, out)
        packages = len((json.loads(out) or {}).get("artifacts") or [])
        rc, out, err = run([*jail(docker), "-e", "GRYPE_DB_CACHE_DIR=/db", "-e", "TMPDIR=/db/.tmp",
                            "-e", "GRYPE_DB_AUTO_UPDATE=false", "-e", "GRYPE_DB_VALIDATE_AGE=false",
                            "-v", f"{ROOT / 'grype-db'}:/db", "-v", f"{sbom}:/sbom.json:ro",
                            grype, "sbom:/sbom.json", "-o", "json", "-q"])
        if rc:
            return {**row, "state": "UNKNOWN", "why": f"grype: {err.strip()[-200:]}", "packages": packages}
        return {**row, "state": "scanned", "packages": packages, **tally(json.loads(out))}
    except (OSError, ValueError) as e:
        return {**row, "state": "UNKNOWN", "why": f"{type(e).__name__}: {e}"}
    finally:
        tar.unlink(missing_ok=True)


def write(path: Path, text: str) -> None:
    """0600, atomically: a half-written report must not read as a short one."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def collect(only: str | None, update: bool) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    base = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "images": []}
    pins = ni.resolved(["syft_image", "grype_image"])
    bad = [k for k, v in pins.items() if not PINNED.match(str(v))]
    docker = docker_bin()
    if bad or docker is None:
        why = f"pin without a digest: {', '.join(bad)}" if bad else "docker not found"
        return {**base, "refused": why, "db": {"usable": False}, "status": "UNKNOWN", "exit": 11}
    for d in (ROOT, ROOT / "grype-db", ROOT / "grype-db" / ".tmp", ROOT / "work", ROOT / "sboms"):
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        d.chmod(0o700)
    def grype_db(*sub: str, network: bool = False) -> list[str]:
        return [*jail(docker, network=network), "-e", "GRYPE_DB_CACHE_DIR=/db", "-e", "TMPDIR=/db/.tmp",
                "-v", f"{ROOT / 'grype-db'}:/db", pins["grype_image"], "db", *sub]
    if update:
        run(grype_db("update", "-q", network=True))  # a failed update leaves the cached DB; db_state judges it
    _, out, _ = run(grype_db("status", "-o", "json"), timeout=120)
    try:
        status = json.loads(out)
    except ValueError:
        status = None
    db = db_state(status, now)
    containers = _cs.inspect(docker)
    if containers is None:
        return {**base, "db": db, "refused": "docker inspect unreadable", "status": "UNKNOWN", "exit": 11}
    imgs = [i for i in running_images(containers) if only in (None, i["ref"], i["id"])]
    rows = [scan(docker, i, pins["syft_image"], pins["grype_image"]) if db["usable"]
            else {"ref": i["ref"], "id": i["id"], "state": "UNKNOWN", "why": "no usable grype DB"} for i in imgs]
    status_, code = verdict(rows, db, None)
    return {**base, "db": db, "images": rows, "status": status_, "exit": code}


def selftest() -> int:
    now = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)
    c = lambda name, image, ref, up=True: {"Name": "/" + name, "Image": image, "Config": {"Image": ref},  # noqa: E731
                                           "State": {"Running": up}}
    imgs = running_images([c("a", "sha256:1", "x:1"), c("b", "sha256:1", "x:1"), c("c", "sha256:2", "y:2"),
                           c("d", "sha256:3", "z:3", up=False)])
    assert [(i["id"], i["containers"]) for i in imgs] == [("sha256:1", ["a", "b"]), ("sha256:2", ["c"])], imgs
    assert db_state(None, now)["usable"] is False
    assert db_state({"valid": False, "error": "database does not exist"}, now)["why"] == "database does not exist"
    assert db_state({"valid": True, "built": "2026-11-11T06:21:32Z"}, now)["stale"] is False
    assert db_state({"valid": True, "built": "2026-11-01T00:00:00Z"}, now)["stale"] is True
    assert db_state({"valid": True, "built": "garbage"}, now)["stale"] is True
    t = tally({"matches": [{"vulnerability": {"id": "CVE-1", "severity": "Critical", "fix": {"state": "fixed"}}},
                           {"vulnerability": {"id": "CVE-2", "severity": "Critical", "fix": {"state": "not-fixed"}}},
                           {"vulnerability": {"id": "CVE-3", "severity": "High"}}]})
    assert t == {"severity": {"Critical": 2, "High": 1}, "critical_fixable": ["CVE-1"]}, t
    fresh = {"usable": True, "stale": False}
    assert verdict([{"state": "scanned", "critical_fixable": []}], fresh, None) == ("ok", 0)
    assert verdict([{"state": "scanned", "critical_fixable": ["CVE-1"]}], fresh, None) == ("findings", 10)
    assert verdict([{"state": "UNKNOWN"}], fresh, None)[1] == 11
    assert verdict([], {"usable": True, "stale": True}, None)[1] == 11
    assert verdict([], {"usable": False}, None)[1] == 11
    assert verdict([], fresh, "pin without a digest")[1] == 11
    assert PINNED.match("anchore/syft:v1.57.1@sha256:" + "0" * 64) and not PINNED.match("anchore/syft:latest")
    assert "--network" in jail("docker") and "--network" not in jail("docker", network=True)
    assert not any("docker.sock" in a for a in jail("docker"))
    print("selftest OK: images / DB usable+stale / tally / verdict 0-10-11 / digest pin / jail")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--image", help="scan only this running image (its ref or id)")
    ap.add_argument("--no-db-update", action="store_true", help="scan with the cached DB")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    r = collect(a.image, not a.no_db_update)
    if ROOT.is_dir() and not a.image:
        write(ROOT / "last.json", json.dumps(r, indent=2))
    if a.json:
        print(json.dumps(r, indent=2))
        return r["exit"]
    db = r["db"]
    print(f"image-sbom: {r['status']} · DB " + ("UNUSABLE" if not db.get("usable") else
          f"{db.get('built', '?')}{' STALE' if db.get('stale') else ''}") + (f" · {r['refused']}" if r.get("refused") else ""))
    for i in r["images"]:
        tail = i.get("why") or f"{i['packages']} pkgs {i['severity']}" + (
            f" fixable critical: {', '.join(i['critical_fixable'])}" if i["critical_fixable"] else "")
        print(f"  {i['state']:<8} {i['ref']:<48} {tail}")
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
