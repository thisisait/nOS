"""A frankenphp pin moves only to bytes upstream's release workflow signed, copied into our mirror.

php/frankenphp re-uploads every release's assets nightly from its main branch (--clobber); a fixed
sha256 on upstream's URL broke Integration on 11-01, 11-04, 11-13 and 11-14. Operator ruling
2026-11-14: mirror the attested binary into a release of this repo and pin that copy.
tools/frankenphp-repin.py --mirror must never take a changed asset on GitHub's word:
`gh attestation verify --signer-workflow static.yaml` decides, the source ref must be the tag or
main, and a mirrored asset is never overwritten. This runs the tool against the real
default.config.yml shape with a fake `gh` on PATH.
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
repo=""; for a in "$@"; do [ "$prev" = -R ] && repo="$a"; prev="$a"; done
case "$1 $2" in
  "release view")
    if [ "$repo" = thisisait/nOS ]; then [ -n "$MIRROR_HAS" ] || exit 1; printf '%s\n' $MIRROR_HAS
    else printf 'frankenphp-linux-x86_64\nfrankenphp-linux-aarch64\nfrankenphp-mac-arm64\n'; fi ;;
  "release download")
    while [ $# -gt 0 ]; do case "$1" in -p) n="$2"; shift 2;; -D) d="$2"; shift 2;; *) shift;; esac; done
    if [ "$repo" = thisisait/nOS ]; then printf '%s' "$MIRROR_BYTES" > "$d/$n"
    elif [ "$n" = frankenphp-linux-x86_64 ]; then printf '%s' "$NEW_BYTES" > "$d/$n"; else cp "$OLD_FILE" "$d/$n"; fi ;;
  "attestation verify")
    [ "$ATTEST_RC" = 0 ] || exit "$ATTEST_RC"
    printf '[{"verificationResult":{"signature":{"certificate":{"sourceRepositoryRef":"%s","sourceRepositoryDigest":"%s"}}}}]' \
      "$ATTEST_REF" "FAKE_SOURCE_COMMIT" ;;
esac
"""


def _run(tmp: Path, *args: str, attest_rc: int = 0, ref: str = "refs/heads/main", mirror_has: str = "",
         mirror_bytes: str = ""):
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
    (tmp / "gh.log").write_text("")
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GH_LOG=str(tmp / "gh.log"),
               ATTEST_RC=str(attest_rc), ATTEST_REF=ref, OLD_FILE=str(old), NEW_BYTES=NEW.decode(),
               MIRROR_HAS=mirror_has, MIRROR_BYTES=mirror_bytes)
    p = subprocess.run([sys.executable, str(TOOL), "--config", str(cfg), *args],
                       env=env, capture_output=True, text=True, timeout=60)
    return p, text, cfg.read_text(), (tmp / "gh.log").read_text()


def test_an_unattested_change_is_refused_and_nothing_written(tmp_path):
    p, before, after, log = _run(tmp_path, "--mirror", attest_rc=1)
    assert p.returncode == 2, p.stdout + p.stderr
    assert after == before, "a changed asset without upstream's attestation was pinned"
    assert "release create" not in log and "release upload" not in log, log


def test_a_build_of_another_ref_is_refused(tmp_path):
    p, before, after, log = _run(tmp_path, "--mirror", ref="refs/heads/some-branch")
    assert p.returncode == 2 and after == before, p.stdout + p.stderr
    assert "release upload" not in log, log


def test_an_attested_build_is_mirrored_and_pinned(tmp_path):
    p, before, after, log = _run(tmp_path, "--mirror")
    assert p.returncode == 0, p.stdout + p.stderr
    new_sha = hashlib.sha256(NEW).hexdigest()
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert any(f'linux-x86_64: "{new_sha}"' in b for _, b in changed), changed
    assert all("linux-x86_64" in b or "as rebuilt" in b for _, b in changed), changed
    assert "--signer-workflow php/frankenphp/.github/workflows/static.yaml" in log, log
    create = next(line for line in log.splitlines() if line.startswith("release create"))
    assert "mirror-frankenphp-v" in create and "--prerelease" in create and "--latest=false" in create, create
    upload = next(line for line in log.splitlines() if line.startswith("release upload"))
    assert "--clobber" not in upload, "a mirror asset must never be overwritten"


def test_the_mirror_is_never_overwritten(tmp_path):
    p, before, after, log = _run(tmp_path, "--mirror", mirror_has="frankenphp-linux-x86_64",
                                 mirror_bytes="other-bytes")
    assert p.returncode == 2 and after == before, p.stdout + p.stderr
    assert "release upload" not in log, log


def test_report_mode_writes_nothing(tmp_path):
    p, before, after, log = _run(tmp_path, mirror_has="frankenphp-linux-x86_64", mirror_bytes="other-bytes")
    assert p.returncode == 1 and after == before, p.stdout
    assert "release create" not in log and "release upload" not in log, log
