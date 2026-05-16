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

Usage
-----

    # Default — write to ~/.nos/secrets.yml (idempotent: replace if exists)
    python3 tools/fetch-authentik-bootstrap-token.py

    # Stdout-only (CI / piping)
    python3 tools/fetch-authentik-bootstrap-token.py --output -

    # Custom file
    python3 tools/fetch-authentik-bootstrap-token.py --output /tmp/tok.yml

Password discovery (in order)
-----------------------------

    1. ``--password <p>`` flag
    2. ``--password -`` (read from stdin, one line)
    3. ``AUTHENTIK_BOOTSTRAP_PASSWORD`` env var
    4. Compute from ``{global_password_prefix}_pw_authentik_admin`` by
       reading ``credentials.yml`` / ``config.yml`` (matches the playbook's
       jinja template at default.credentials.yml:authentik_bootstrap_password).
    5. Interactive prompt (only if stdin is a TTY).

URL discovery
-------------

    1. ``--url <u>`` flag
    2. ``AUTHENTIK_BOOTSTRAP_URL`` env var
    3. ``http://127.0.0.1:9003`` (loopback default; matches authentik_port).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path

import requests
import urllib3
import yaml


DEFAULT_URL = "http://127.0.0.1:9003"
DEFAULT_FLOW_SLUG = "default-authentication-flow"
DEFAULT_SECRETS_PATH = os.path.expanduser("~/.nos/secrets.yml")
DEFAULT_USERNAME = "akadmin"
TOKEN_IDENTIFIER = "nos-api"
TOKEN_KEY_NAME = "authentik_bootstrap_token"


# ── Password discovery ────────────────────────────────────────────────────


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open("r") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, yaml.YAMLError):
        return {}


def _resolve_password(repo_root: Path, cli_value: str | None) -> str:
    """Apply the documented precedence chain."""
    if cli_value == "-":
        line = sys.stdin.readline().rstrip("\n")
        if not line:
            raise SystemExit("ERROR: --password - was set but stdin was empty")
        return line
    if cli_value:
        return cli_value

    env = os.environ.get("AUTHENTIK_BOOTSTRAP_PASSWORD")
    if env:
        return env

    # Compute from {prefix}_pw_authentik_admin (matches default.credentials.yml).
    # Operator-side config.yml's prefix wins over credentials.yml in the
    # playbook's vars_files order (config last). Mirror that here so the
    # script computes the SAME value the playbook fed Authentik.
    config = _read_yaml(repo_root / "config.yml")
    credentials = _read_yaml(repo_root / "credentials.yml")
    prefix = config.get("global_password_prefix") or credentials.get("global_password_prefix")
    if prefix:
        return f"{prefix}_pw_authentik_admin"

    if sys.stdin.isatty():
        return getpass.getpass(f"akadmin password (for {DEFAULT_USERNAME}@Authentik): ")

    raise SystemExit(
        "ERROR: cannot resolve akadmin password. Pass --password, set "
        "AUTHENTIK_BOOTSTRAP_PASSWORD, or ensure global_password_prefix is "
        f"defined in config.yml / credentials.yml at {repo_root}."
    )


# ── Authentik flow login ──────────────────────────────────────────────────


class FlowLoginError(RuntimeError):
    pass


def _flow_login(base_url: str, username: str, password: str,
                flow_slug: str, timeout_s: float = 15,
                verify_tls: bool = False) -> requests.Session:
    """Drive the Authentik flow executor headlessly. Mirrors
    ``tests/e2e/lib/authentik_login.py`` but self-contained so this CLI has
    no test-tree imports.
    """
    if not verify_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    flow_url = f"{base_url}/api/v3/flows/executor/{flow_slug}/"
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": "nos-fetch-bootstrap-token/1.0",
        "Accept": "application/json",
    })

    def _stage(payload: dict, label: str) -> dict:
        try:
            r = sess.post(flow_url, json=payload, timeout=timeout_s, verify=verify_tls)
        except requests.RequestException as exc:
            raise FlowLoginError(f"{label}: request failed: {exc}") from exc
        if r.status_code >= 400:
            raise FlowLoginError(f"{label}: HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json() if r.content else {}
        except (ValueError, requests.JSONDecodeError):
            return {}

    # Prime the flow (sets the cookie).
    try:
        sess.get(flow_url, timeout=timeout_s, verify=verify_tls)
    except requests.RequestException as exc:
        raise FlowLoginError(f"flow prime failed: {exc}") from exc

    body = _stage({"uid_field": username}, "identification")
    if isinstance(body, dict) and "deny" in body.get("component", ""):
        raise FlowLoginError(f"identification denied: {body.get('component')}")

    body = _stage({"password": password}, "password")
    component = body.get("component", "") if isinstance(body, dict) else ""
    if "deny" in component or "access-denied" in component:
        raise FlowLoginError(f"password denied: component={component}")

    sess.verify = verify_tls
    return sess


# ── Token retrieval ───────────────────────────────────────────────────────


class TokenFetchError(RuntimeError):
    pass


def _fetch_token_key(sess: requests.Session, base_url: str,
                     identifier: str, timeout_s: float = 10) -> str:
    """List → pk → view_key. Two round-trips because the list endpoint omits
    the secret; only ``/view_key/`` returns it."""
    list_url = f"{base_url}/api/v3/core/tokens/?identifier={identifier}"
    r = sess.get(list_url, timeout=timeout_s)
    if r.status_code != 200:
        raise TokenFetchError(f"list tokens HTTP {r.status_code}: {r.text[:200]}")
    results = r.json().get("results", [])
    if not results:
        raise TokenFetchError(
            f"no token with identifier={identifier!r} found in Authentik. "
            "Has the playbook applied roles/pazny.authentik blueprints?"
        )
    # The Authentik token PK is a UUID string, but the API uses the
    # ``identifier`` directly as the URL slug on /view_key/. Try both —
    # identifier-as-slug is more idiomatic per Authentik docs.
    view_url = f"{base_url}/api/v3/core/tokens/{identifier}/view_key/"
    r = sess.get(view_url, timeout=timeout_s)
    if r.status_code != 200:
        # Fallback: try the pk directly
        pk = results[0].get("pk") or results[0].get("identifier")
        view_url = f"{base_url}/api/v3/core/tokens/{pk}/view_key/"
        r = sess.get(view_url, timeout=timeout_s)
        if r.status_code != 200:
            raise TokenFetchError(
                f"view_key for {identifier} HTTP {r.status_code}: {r.text[:200]}"
            )
    key = r.json().get("key")
    if not key:
        raise TokenFetchError(f"view_key response missing 'key': {r.text[:200]}")
    return key


# ── secrets.yml write ─────────────────────────────────────────────────────


_KEY_LINE_RE = re.compile(rf"^{re.escape(TOKEN_KEY_NAME)}\s*:.*$", re.MULTILINE)


def _write_secret(secrets_path: str, token: str) -> str:
    """Idempotently upsert ``authentik_bootstrap_token: "<token>"`` into the
    target file. Returns a short status string (``replaced`` / ``appended`` /
    ``created``).

    Uses plain-text manipulation rather than ruamel/yaml round-trip to avoid
    re-quoting unrelated values or reformatting the operator's hand-curated
    file. The key/value shape is fixed and predictable.
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
        "--url", default=os.environ.get("AUTHENTIK_BOOTSTRAP_URL", DEFAULT_URL),
        help=f"Authentik base URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--username", default=DEFAULT_USERNAME,
        help=f"Authentik admin username (default: {DEFAULT_USERNAME})",
    )
    parser.add_argument(
        "--password", default=None,
        help="Admin password. Pass '-' to read from stdin. "
             "Otherwise resolved from env / config — see docstring.",
    )
    parser.add_argument(
        "--flow-slug", default=DEFAULT_FLOW_SLUG,
        help=f"Authentication flow slug (default: {DEFAULT_FLOW_SLUG})",
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
        "--verify-tls", action="store_true",
        help="Verify TLS certs (default: off, matches mkcert dev setup)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    password = _resolve_password(repo_root, args.password)
    base_url = args.url.rstrip("/")

    print(f"[fetch-bootstrap-token] logging in as {args.username}@{base_url}…",
          file=sys.stderr)
    try:
        sess = _flow_login(
            base_url=base_url, username=args.username, password=password,
            flow_slug=args.flow_slug, verify_tls=args.verify_tls,
        )
    except FlowLoginError as exc:
        print(f"ERROR: login failed: {exc}", file=sys.stderr)
        return 2

    print(f"[fetch-bootstrap-token] retrieving token '{args.identifier}'…",
          file=sys.stderr)
    try:
        token = _fetch_token_key(sess, base_url, args.identifier)
    except TokenFetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.output == "-":
        # Plain key=value for shell piping (operator uses `eval "$(...)"`-style),
        # but we keep YAML shape because that's what the spec docs reference.
        sys.stdout.write(f'{TOKEN_KEY_NAME}: "{token}"\n')
        return 0

    status = _write_secret(args.output, token)
    print(f"[fetch-bootstrap-token] {args.output}: {status} "
          f"({TOKEN_KEY_NAME}=*** (len={len(token)}))",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
