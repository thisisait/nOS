"""Anatomy gate — a mounted mkcert root CA must also be TRUSTED.

test_mkcert_ca_mount_is_guarded.py pins WHEN the estate CA may reach a
container. This gate pins the other half: once it is there, something must
make a TLS client believe it. A bind mount into
``/usr/local/share/ca-certificates/`` is inert until ``update-ca-certificates``
runs, and a file dropped into ``/etc/ssl/certs/`` without a hash link is
inert to OpenSSL and Node alike.

Measured on a fresh local-TLD install (thisisait/nOS#53): Nextcloud and
BookStack mounted the CA, never ran ``update-ca-certificates``, and every
OIDC sign-in failed with ``ssl_verify_result=20``. The Nextcloud fragment
even carried a comment claiming the image ran it. WordPress and Miniflux had
the same shape and were caught by this gate, not by an operator.

ACCEPTED TRUST MECHANISMS, per mounted container path P (dir D):

  * ``update-ca-certificates`` in the fragment's live text (entrypoint or
    command wrapper) and P is a ``*.crt`` under
    ``/usr/local/share/ca-certificates`` — the only place it reads;
  * P named again on a non-mount line — an env var handing the file to the
    client (``NODE_EXTRA_CA_CERTS``, ``REQUESTS_CA_BUNDLE``,
    ``GF_AUTH_GENERIC_OAUTH_TLS_CLIENT_CA``, …), whatever it is called;
  * ``SSL_CERT_DIR`` listing D (Go reads every file there, no hash links);
  * D in SELF_TRUSTING below, each with the reason the image trusts it.

Comments do not count: a comment saying "the image runs it" is exactly how
#53 shipped.

CEILING, NAMED. This is a source scan. It proves a mechanism is declared,
not that the image's entrypoint path is right, that the container runs as
root (``update-ca-certificates`` needs it) or that the app's HTTP client
reads the system store. Those were measured once for #53 with a TLS server
signed by a throwaway CA (bookstack, nextcloud, wordpress: FAIL without the
wrapper, OK with it; miniflux: FAIL without SSL_CERT_DIR, OK with it). An
image bump that moves its entrypoint is a converge failure, not a silent one.

CI-safe: pure source scan.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

HOST_CA = "shared-certs/rootCA.pem"
_MOUNT = re.compile(re.escape(HOST_CA) + r":([^\s:\"']+)")
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.S)
_SSL_CERT_DIR = re.compile(r"SSL_CERT_DIR\s*[:=]\s*[\"']?([^\"'\n]+)")

UPDATE_CA_DIR = "/usr/local/share/ca-certificates"

#: Directories an image trusts on its own, and why.
SELF_TRUSTING = {
    # Omnibus `gitlab-ctl reconfigure` links every cert here into its bundle.
    "/etc/gitlab/trusted-certs": "gitlab omnibus trusted-certs",
}


def _scan_set() -> list[Path]:
    out: list[Path] = []
    for pattern in ("files/anatomy/plugins/*/templates/*",
                    "roles/*/templates/**/*",
                    "templates/**/*",
                    "apps/*.yml"):
        out += [p for p in REPO.glob(pattern) if p.is_file()]
    return sorted(set(out))


def _live_lines(text: str) -> list[str]:
    """Lines that are not comments (Jinja `{# #}` or YAML full-line `#`)."""
    text = _JINJA_COMMENT.sub("", text)
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def _untrusted(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if HOST_CA not in text:
        return []
    lines = _live_lines(text)
    live = "\n".join(lines)
    cert_dirs = {d.rstrip("/") for m in _SSL_CERT_DIR.finditer(live)
                 for d in m.group(1).split(":")}
    out = []
    for target in sorted({m.group(1) for m in _MOUNT.finditer(live)}):
        d = posixpath.dirname(target)
        if d in SELF_TRUSTING or d in cert_dirs:
            continue
        if any(target in ln and HOST_CA not in ln for ln in lines):
            continue
        if (d == UPDATE_CA_DIR and target.endswith(".crt")
                and "update-ca-certificates" in live):
            continue
        out.append(f"{path.relative_to(REPO)}: {target}")
    return out


def test_the_scan_sees_ca_mounts():
    """Blind-gate guard: the scan must find the mounts it exists to judge."""
    mounting = [p for p in _scan_set()
                if HOST_CA in p.read_text(encoding="utf-8", errors="replace")]
    assert len(mounting) >= 5, f"only {len(mounting)} CA-mounting files found"


def test_every_mounted_ca_is_trusted():
    offenders = [o for p in _scan_set() for o in _untrusted(p)]
    assert not offenders, (
        "mkcert CA mounted but nothing makes the client trust it — add an "
        "update-ca-certificates entrypoint wrapper (see vaultwarden-base), an "
        "env var naming the file, or SSL_CERT_DIR (Go):\n  "
        + "\n  ".join(offenders)
    )
