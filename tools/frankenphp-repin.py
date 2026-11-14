#!/usr/bin/env python3
"""Pin frankenphp_checksums to OUR mirror of the static binaries, filled only with what upstream's
own release workflow signed.

php/frankenphp re-uploads every release's assets nightly from its `main` branch (--clobber), so a
pin on upstream's URL went stale within a day (dev nightly red 11-13 and 11-14), and no asset was
ever built from its tag (attestation source refs/heads/main, v1.13.4 and v1.13.5 alike). Operator
ruling 2026-11-14: mirror the attested binary into a release of this repo and pin that copy, so the
digest stops moving; the trust stays upstream's signed build, as before.

  tools/frankenphp-repin.py              # report: do the pins match the mirror's assets
  tools/frankenphp-repin.py --mirror     # copy upstream's attested assets into the mirror, write pins
Exit: 0 pins match (or were written), 1 a pin differs from the mirror, 2 an asset failed attestation
or the mirror already holds different bytes (nothing written), 3 a release or the pin block could
not be read.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))
import nos_identity as ni  # noqa: E402
UPSTREAM = "php/frankenphp"
MIRROR = "thisisait/nOS"
SIGNER = "php/frankenphp/.github/workflows/static.yaml"
VERSION = re.compile(r'^frankenphp_version:\s*"([^"]+)"', re.M)
PIN = re.compile(r'^(  )([a-z0-9_-]+): "([0-9a-f]{64})"', re.M)
DATED = re.compile(r"(of v[\d.]+ as rebuilt )\d{4}-\d{2}-\d{2}( ~[\d:]+ UTC)?")


def mirror_tag(version: str) -> str:
    """Not `v*`: that prefix is this repo's release namespace (pages.yml deploys on it)."""
    return f"mirror-frankenphp-v{version}"


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def pin_block(text: str) -> tuple[int, int]:
    start = text.index("frankenphp_checksums:\n") + len("frankenphp_checksums:\n")
    end = start
    for line in text[start:].splitlines(keepends=True):
        if not line.startswith("  "):
            break
        end += len(line)
    return start, end


def assets(repo: str, tag: str) -> set[str] | None:
    r = gh("release", "view", tag, "-R", repo, "--json", "assets", "--jq", ".assets[].name")
    return set(r.stdout.split()) if r.returncode == 0 else None


def fetch(repo: str, tag: str, name: str, tmp: str) -> tuple[Path | None, str]:
    got = gh("release", "download", tag, "-R", repo, "-p", name, "-D", tmp, "--clobber")
    path = Path(tmp) / name
    if got.returncode != 0 or not path.is_file():
        return None, got.stderr.strip()
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def attested_source(path: Path, version: str) -> str | None:
    """The source ref upstream's signer built this file from, if it is the tag or main; else None."""
    att = gh("attestation", "verify", str(path), "-R", UPSTREAM, "--signer-workflow", SIGNER, "--format", "json")
    if att.returncode != 0:
        return None
    try:
        cert = json.loads(att.stdout)[0]["verificationResult"]["signature"]["certificate"]
        ref, commit = cert["sourceRepositoryRef"], cert["sourceRepositoryDigest"]
    except (ValueError, LookupError, TypeError):
        return None
    # the operator's trust (2026-11-14): upstream's signed build of its tag or of main, nothing else
    return f"{ref}@{commit[:12]}" if ref in (f"refs/tags/v{version}", "refs/heads/main") else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--mirror", action="store_true", help="copy upstream's attested assets into the mirror, write pins")
    ap.add_argument("--config", help="default: the committed layer that declares frankenphp_checksums")
    a = ap.parse_args(argv)
    cfg = Path(a.config) if a.config else next(
        (f for f in ni.default_layers() if "frankenphp_checksums:\n" in f.read_text(encoding="utf-8")), None)
    if cfg is None:
        print("no committed layer declares frankenphp_checksums", file=sys.stderr)
        return 3
    text = cfg.read_text(encoding="utf-8")
    try:
        version = VERSION.search(text).group(1)
        start, end = pin_block(text)
    except (AttributeError, ValueError):
        print(f"cannot read frankenphp_version / frankenphp_checksums in {cfg}", file=sys.stderr)
        return 3
    tag, block = mirror_tag(version), text[start:end]
    keys = [(k, p) for _, k, p in PIN.findall(block)]
    mirrored = assets(MIRROR, tag)
    if not a.mirror:
        if mirrored is None:
            print(f"no mirror release {MIRROR}@{tag}: run --mirror", file=sys.stderr)
            return 1
        bad = 0
        with tempfile.TemporaryDirectory() as tmp:
            for key, pinned in keys:
                name = f"frankenphp-{key}"
                if name not in mirrored:
                    print(f"  -      {key}: not mirrored; pin kept (the fetch fails closed)")
                    continue
                path, digest = fetch(MIRROR, tag, name, tmp)
                if path is None:
                    print(f"cannot download {name} from the mirror: {digest}", file=sys.stderr)
                    return 3
                ok = digest == pinned
                bad += not ok
                print(f"  {'ok    ' if ok else 'DIFFER'} {key}: pin {pinned[:12]}, mirror {digest[:12]}")
        return 1 if bad else 0

    upstream = assets(UPSTREAM, f"v{version}")
    if upstream is None:
        print(f"cannot list {UPSTREAM} v{version} assets", file=sys.stderr)
        return 3
    plan: dict[str, tuple[Path, str, str]] = {}
    refused = []
    tmp = tempfile.mkdtemp()
    for key, _ in keys:
        name = f"frankenphp-{key}"
        if name not in upstream:
            print(f"  -      {key}: no {name} asset in v{version}; pin kept")
            continue
        path, digest = fetch(UPSTREAM, f"v{version}", name, tmp)
        if path is None:
            print(f"cannot download {name}: {digest}", file=sys.stderr)
            return 3
        src = attested_source(path, version)
        if src is None:
            refused.append(key)
            print(f"  REFUSE {key}: {digest[:12]} is not {SIGNER}'s build of the tag or main")
            continue
        if mirrored and name in mirrored:
            _, have = fetch(MIRROR, tag, name, tempfile.mkdtemp())
            if have != digest:
                refused.append(key)
                print(f"  REFUSE {key}: the mirror already holds {have[:12]}; a mirror is never overwritten")
                continue
        plan[key] = (path, digest, src)
        print(f"  mirror {key}: {digest[:12]} ({src})")
    if refused:
        print(f"REFUSED: {len(refused)} asset(s); nothing uploaded or written")
        return 2
    if mirrored is None:
        notes = "\n".join(f"- frankenphp-{k}: sha256 {d}, built by {SIGNER} from {s}" for k, (_, d, s) in plan.items())
        made = gh("release", "create", tag, "-R", MIRROR, "--prerelease", "--latest=false",
                  "--title", f"Mirror: FrankenPHP {version} static binaries (upstream-attested)",
                  "--notes", f"Pinned copies for the nOS converge (tools/frankenphp-repin.py --mirror).\n\n{notes}")
        if made.returncode != 0:
            print(f"cannot create {MIRROR}@{tag}: {made.stderr.strip()}", file=sys.stderr)
            return 3
        mirrored = set()
    new = [str(p) for k, (p, _, _) in plan.items() if f"frankenphp-{k}" not in mirrored]
    if new:
        up = gh("release", "upload", tag, "-R", MIRROR, *new)  # no --clobber: an existing asset stays
        if up.returncode != 0:
            print(f"upload to {MIRROR}@{tag} failed: {up.stderr.strip()}", file=sys.stderr)
            return 3
    changed = {k: d for k, (_, d, _) in plan.items()}
    block = PIN.sub(lambda m: f'{m.group(1)}{m.group(2)}: "{changed.get(m.group(2), m.group(3))}"', block)
    head = DATED.sub(lambda m: m.group(1) + datetime.date.today().isoformat(), text[:start], count=1)
    cfg.write_text(head + block + text[end:], encoding="utf-8")
    print(f"mirrored {len(new)} asset(s) to {MIRROR}@{tag}; wrote {len(changed)} pin(s) to {cfg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
