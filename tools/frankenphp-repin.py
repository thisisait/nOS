#!/usr/bin/env python3
"""Re-pin frankenphp_checksums to the current release assets, but only what upstream's own
release workflow signed.

php/frankenphp rebuilds its LATEST tag every night and re-uploads the assets (--clobber), so a
sha256 pin goes stale within days (master Integration red 11-01 and 11-04; row
frankenphp-nightly-digest). The install keeps pinning bytes; this moves the pin, and moves it only
for a file `gh attestation verify` proves was built by SIGNER — never a digest GitHub merely lists.

  tools/frankenphp-repin.py              # report: which pins are stale (needs gh, network)
  tools/frankenphp-repin.py --write      # rewrite the stale ones in default.config.yml
Exit: 0 nothing stale or rewritten, 1 stale (report mode), 2 a changed asset failed attestation
(nothing written), 3 the release or the pin block could not be read.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "php/frankenphp"
SIGNER = "php/frankenphp/.github/workflows/static.yaml"
VERSION = re.compile(r'^frankenphp_version:\s*"([^"]+)"', re.M)
PIN = re.compile(r'^(  )([a-z0-9_-]+): "([0-9a-f]{64})"', re.M)
DATED = re.compile(r"(of v[\d.]+ as rebuilt )\d{4}-\d{2}-\d{2}( ~[\d:]+ UTC)?")


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--config", default=str(REPO_ROOT / "default.config.yml"))
    a = ap.parse_args(argv)
    cfg = Path(a.config)
    text = cfg.read_text(encoding="utf-8")
    try:
        version = VERSION.search(text).group(1)
        start, end = pin_block(text)
    except (AttributeError, ValueError):
        print(f"cannot read frankenphp_version / frankenphp_checksums in {cfg}", file=sys.stderr)
        return 3
    listed = gh("release", "view", f"v{version}", "-R", UPSTREAM, "--json", "assets", "--jq", ".assets[].name")
    if listed.returncode != 0:
        print(f"cannot list v{version} assets: {listed.stderr.strip()}", file=sys.stderr)
        return 3
    assets = set(listed.stdout.split())
    block, changed, refused = text[start:end], {}, []
    with tempfile.TemporaryDirectory() as tmp:
        for _, key, pinned in PIN.findall(block):
            name = f"frankenphp-{key}"
            if name not in assets:
                print(f"  -      {key}: no {name} asset in v{version}; pin kept")
                continue
            got = gh("release", "download", f"v{version}", "-R", UPSTREAM, "-p", name, "-D", tmp, "--clobber")
            path = Path(tmp) / name
            if got.returncode != 0 or not path.is_file():
                print(f"cannot download {name}: {got.stderr.strip()}", file=sys.stderr)
                return 3
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest == pinned:
                print(f"  ok     {key}: pin current")
                continue
            att = gh("attestation", "verify", str(path), "-R", UPSTREAM, "--signer-workflow", SIGNER)
            if att.returncode != 0:
                refused.append(key)
                print(f"  REFUSE {key}: {digest[:12]} is not signed by {SIGNER}: {att.stderr.strip()[:200]}")
                continue
            changed[key] = digest
            print(f"  stale  {key}: {pinned[:12]} -> {digest[:12]} (attested by {SIGNER})")
    if refused:
        print(f"REFUSED: {len(refused)} changed asset(s) without upstream's attestation; nothing written")
        return 2
    if not changed:
        return 0
    if not a.write:
        print(f"{len(changed)} pin(s) stale; --write rewrites them")
        return 1
    block = PIN.sub(lambda m: f'{m.group(1)}{m.group(2)}: "{changed.get(m.group(2), m.group(3))}"', block)
    head = DATED.sub(lambda m: m.group(1) + datetime.date.today().isoformat(), text[:start], count=1)
    cfg.write_text(head + block + text[end:], encoding="utf-8")
    print(f"wrote {len(changed)} pin(s) to {cfg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
