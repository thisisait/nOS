"""A frankenphp pin moves only to bytes upstream's release workflow signed.

php/frankenphp re-uploads its latest tag's assets every night (--clobber); a fixed sha256 broke
master Integration on 11-01 and 11-04. tools/frankenphp-repin.py re-pins, and must never take a
changed asset on GitHub's word: `gh attestation verify --signer-workflow static.yaml` decides.
This runs the tool against the real default.config.yml shape with a fake `gh` on PATH.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
TOOL = REPO / "tools/frankenphp-repin.py"
NEW = b"rebuilt-binary-bytes"

FAKE_GH = r"""#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "release view") printf 'frankenphp-linux-x86_64\nfrankenphp-linux-aarch64\nfrankenphp-mac-arm64\n' ;;
  "release download")
    while [ $# -gt 0 ]; do case "$1" in -p) n="$2"; shift 2;; -D) d="$2"; shift 2;; *) shift;; esac; done
    if [ "$n" = frankenphp-linux-x86_64 ]; then printf '%s' "$NEW_BYTES" > "$d/$n"; else cp "$OLD_FILE" "$d/$n"; fi ;;
  "attestation verify") exit "$ATTEST_RC" ;;
esac
"""


def _run(tmp: Path, attest_rc: int, *args: str):
    cfg = tmp / "pins.yml"
    cfg.write_text(next(t for t in (f.read_text(encoding="utf-8") for f in ni.default_layers())
                        if "frankenphp_checksums:\n" in t), encoding="utf-8")
    # The unchanged assets serve bytes whose sha IS their pin: make every pin that file's sha.
    old = tmp / "old.bin"
    old.write_bytes(b"pinned-bytes")
    old_sha = hashlib.sha256(old.read_bytes()).hexdigest()
    import re
    text = re.sub(r'^(  (?:linux-x86_64|linux-aarch64|mac-arm64|mac-x86_64)): "[0-9a-f]{64}"',
                  lambda m: f'{m.group(1)}: "{old_sha}"', cfg.read_text(), flags=re.M)
    cfg.write_text(text)
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "gh").write_text(FAKE_GH)
    (bindir / "gh").chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(tmp / "gh.log"),
               ATTEST_RC=str(attest_rc), OLD_FILE=str(old), NEW_BYTES=NEW.decode())
    p = subprocess.run([sys.executable, str(TOOL), "--config", str(cfg), *args],
                       env=env, capture_output=True, text=True, timeout=60)
    return p, text, cfg.read_text(), (tmp / "gh.log").read_text()


def test_an_unattested_change_is_refused_and_nothing_written(tmp_path):
    p, before, after, _ = _run(tmp_path, 1, "--write")
    assert p.returncode == 2, p.stdout + p.stderr
    assert after == before, "a changed asset without upstream's attestation was pinned"


def test_an_attested_change_moves_only_its_own_pin(tmp_path):
    p, before, after, log = _run(tmp_path, 0, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    new_sha = hashlib.sha256(NEW).hexdigest()
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert any(f'linux-x86_64: "{new_sha}"' in b for _, b in changed), changed
    assert all("linux-x86_64" in b or "as rebuilt" in b for _, b in changed), changed
    assert "--signer-workflow php/frankenphp/.github/workflows/static.yaml" in log, log


def test_report_mode_writes_nothing(tmp_path):
    p, before, after, _ = _run(tmp_path, 0)
    assert p.returncode == 1 and after == before, p.stdout
