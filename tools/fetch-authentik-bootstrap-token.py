#!/usr/bin/env python3
"""Retrieve the ``nos-api`` Authentik token and persist it to secrets.yml.

Closes the last manual UI step in the A13.6 ephemeral-tester bootstrap chain.
Without this script, the operator must open the Authentik UI, navigate to
Directory → Tokens → ``nos-api`` → "Copy Key", and paste the value into
``~/.nos/secrets.yml``. Run this once after a blank reset and the value is
written for you.

DOCTRINE — why this is a CLI, not a playbook step
--------------------------------------------------
``docs/e2e-tester-identity.md`` is explicit: the production playbook
intentionally keeps stateless tokens out of the persistent secrets file.
This script preserves that boundary — it runs **on demand** (operator
invocation), not as part of ``ansible-playbook main.yml``. Tokens flow
*outwards* from Authentik to the operator's workstation, never inwards
from a versioned file into the playbook's source-of-truth.

Why docker-exec, not the Authentik API
---------------------------------------
The earlier draft of this script drove ``/api/v3/flows/executor/`` with
the akadmin password and tried to read ``/api/v3/core/tokens/`` with the
returned session cookie. Authentik refuses that path — the
``/core/tokens/`` admin endpoints require a token-authenticated request,
not a cookie-authenticated one, and the only token that satisfies that
is the very token we are trying to retrieve. Bootstrap circularity.

``docker exec <auth-server> ak shell`` short-circuits the chicken-and-egg
problem: we read the token straight out of the Authentik database via
Django ORM. The container's own service account has unrestricted DB
access, no API auth dance needed.

Usage
-----

    # Default — write to ~/.nos/secrets.yml (idempotent: replace if exists)
    python3 tools/fetch-authentik-bootstrap-token.py

    # Stdout-only (CI / piping)
    python3 tools/fetch-authentik-bootstrap-token.py --output -

    # Different identifier or container
    python3 tools/fetch-authentik-bootstrap-token.py --identifier custom-tok
    python3 tools/fetch-authentik-bootstrap-token.py --container nos-authentik-server
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


DEFAULT_SECRETS_PATH = os.path.expanduser("~/.nos/secrets.yml")
TOKEN_IDENTIFIER = "nos-api"
TOKEN_KEY_NAME = "authentik_bootstrap_token"

# Candidate container names (probed in order). The first one matching a
# running container wins. Operators with non-standard compose project
# names can pass ``--container`` explicitly.
DEFAULT_CONTAINER_CANDIDATES = (
    "infra-authentik-server-1",
    "nos-authentik-server",
    "authentik-server",
)


# ── Container discovery ───────────────────────────────────────────────────


class ContainerNotFoundError(RuntimeError):
    pass


def _list_running_containers() -> list[str]:
    """Return all running Docker container names. Empty list if docker
    is missing or daemon is down (we treat both as ``not available``)."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _resolve_container(explicit: str | None) -> str:
    """Pick an Authentik server container to exec into."""
    running = _list_running_containers()
    if not running:
        raise ContainerNotFoundError(
            "no running Docker containers found. Is the daemon up? "
            "Has the playbook deployed the infra stack?"
        )

    if explicit:
        if explicit in running:
            return explicit
        raise ContainerNotFoundError(
            f"container {explicit!r} not running. Running containers: "
            f"{', '.join(running) or '(none)'}"
        )

    for candidate in DEFAULT_CONTAINER_CANDIDATES:
        if candidate in running:
            return candidate

    # Fuzzy fallback — any container whose name matches *authentik*server*.
    fuzzy = [c for c in running if "authentik" in c and "server" in c]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if len(fuzzy) > 1:
        raise ContainerNotFoundError(
            f"multiple Authentik server containers found: {fuzzy}. "
            "Pass --container <name> to disambiguate."
        )

    raise ContainerNotFoundError(
        "no Authentik server container found. Tried: "
        f"{', '.join(DEFAULT_CONTAINER_CANDIDATES)}. "
        f"Running: {', '.join(running)}."
    )


# ── Token retrieval ───────────────────────────────────────────────────────


class TokenFetchError(RuntimeError):
    pass


# Sentinel prefix on the line carrying the secret value. The shell wraps
# output with structured log JSON, so we mark our own line with a unique
# token and grep it back out — avoids fragile last-line parsing.
_SENTINEL = "NOS_TOKEN_OUT:"


def _fetch_token_from_container(container: str, identifier: str,
                                timeout_s: float = 30) -> str:
    """Exec ``ak shell`` inside the Authentik server container, read the
    Token row by identifier via Django ORM, print the key wrapped in our
    sentinel marker, parse it back out.
    """
    snippet = (
        "from authentik.core.models import Token\n"
        f"t = Token.objects.filter(identifier='{identifier}').first()\n"
        f"print('{_SENTINEL}', t.key if t else 'NOT_FOUND')\n"
    )
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", container, "ak", "shell", "-c", snippet],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise TokenFetchError(
            f"ak shell timed out after {timeout_s}s — Authentik may be "
            f"starting up or under load: {exc}"
        ) from exc

    if result.returncode != 0:
        raise TokenFetchError(
            f"ak shell exited {result.returncode}: {result.stderr[-500:]}"
        )

    # Authentik wraps stdout in structured JSON log lines. Find our
    # sentinel marker and pull the value off the same line.
    match = re.search(rf"{re.escape(_SENTINEL)}\s+(\S+)", result.stdout)
    if not match:
        raise TokenFetchError(
            f"sentinel {_SENTINEL!r} not found in ak shell output. "
            f"Tail: {result.stdout[-500:]}"
        )

    value = match.group(1).strip()
    if value == "NOT_FOUND":
        raise TokenFetchError(
            f"no token with identifier={identifier!r} found in Authentik. "
            "Has the playbook applied roles/pazny.authentik's "
            "00-admin-groups.yaml.j2 blueprint?"
        )
    return value


# ── secrets.yml write ─────────────────────────────────────────────────────


_KEY_LINE_RE = re.compile(rf"^{re.escape(TOKEN_KEY_NAME)}\s*:.*$", re.MULTILINE)


def _write_secret(secrets_path: str, token: str) -> str:
    """Idempotently upsert ``authentik_bootstrap_token: "<token>"`` into the
    target file. Returns a short status string (``replaced`` / ``appended`` /
    ``created`` / ``unchanged``).

    Plain-text upsert rather than ruamel/yaml round-trip — avoids re-quoting
    unrelated values or reformatting the operator's hand-curated file. The
    key/value shape is predictable enough that a regex is safer than a
    full YAML parse.
    """
    path = Path(secrets_path)
    new_line = f'{TOKEN_KEY_NAME}: "{token}"'

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_line + "\n")
        os.chmod(path, 0o600)
        return "created"

    content = path.read_text()
    if _KEY_LINE_RE.search(content):
        content_new = _KEY_LINE_RE.sub(new_line, content)
        if content_new == content:
            return "unchanged"
        path.write_text(content_new)
        return "replaced"

    sep = "" if content.endswith("\n") or content == "" else "\n"
    path.write_text(content + sep + new_line + "\n")
    return "appended"


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--container", default=None,
        help=("Authentik server container name. Auto-discovered from "
              + ", ".join(DEFAULT_CONTAINER_CANDIDATES) + " if omitted."),
    )
    parser.add_argument(
        "--identifier", default=TOKEN_IDENTIFIER,
        help=f"Token identifier in Authentik (default: {TOKEN_IDENTIFIER})",
    )
    parser.add_argument(
        "--output", default=DEFAULT_SECRETS_PATH,
        help=(f"Output file (default: {DEFAULT_SECRETS_PATH}, "
              "use '-' for stdout-only)"),
    )
    parser.add_argument(
        "--timeout", type=float, default=30,
        help="Max seconds to wait for ak shell to respond (default: 30)",
    )
    args = parser.parse_args()

    try:
        container = _resolve_container(args.container)
    except ContainerNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"[fetch-bootstrap-token] reading '{args.identifier}' from "
          f"container '{container}'…", file=sys.stderr)
    try:
        token = _fetch_token_from_container(
            container, args.identifier, timeout_s=args.timeout,
        )
    except TokenFetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.output == "-":
        sys.stdout.write(f'{TOKEN_KEY_NAME}: "{token}"\n')
        return 0

    status = _write_secret(args.output, token)
    print(f"[fetch-bootstrap-token] {args.output}: {status} "
          f"({TOKEN_KEY_NAME}=*** (len={len(token)}))", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
