#!/usr/bin/env python3
"""Provision / teardown ephemeral tester identities for Playwright e2e tests.

Mirrors the pytest ``tester_identity`` fixture (see ``tests/e2e/conftest.py``)
in CLI form, so the TypeScript Playwright globalSetup / globalTeardown can
participate in the same A13.6 ephemeral-identity protocol.

Usage:
    # Provision a fresh tester, write JSON descriptor to disk
    python3 tools/e2e-auth-helper.py provision --tier provider \\
        --output /tmp/nos-tester.json

    # Tear it down (delete Authentik user + revoke Wing token)
    python3 tools/e2e-auth-helper.py teardown --input /tmp/nos-tester.json

Output JSON (provision):
    {
      "username":        "nos-tester-e2e-a1b2c3d4",
      "password":        "<urlsafe-32B>",
      "email":           "nos-tester-e2e-a1b2c3d4@<tenant>",
      "tier":            "provider",
      "group_name":      "nos-providers",
      "user_pk":         42,           # ← needed by teardown
      "group_pk":        "uuid",       # ← needed by teardown
      "token_name":      "tester:e2e:nos-tester-e2e-a1b2c3d4",
      "token_plaintext": "<bearer>"    # in-memory only; do not commit
    }

Env vars:
    AUTHENTIK_API_URL    — Authentik admin API (default: http://127.0.0.1:9003/api/v3)
    AUTHENTIK_API_TOKEN  — Authentik admin token (required)
    WING_DATA_DIR        — wing.db location (default: ~/wing/data)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Make ``tests.e2e.lib.*`` importable as a package — its relative imports
# require it (matches how sweep-orphan-testers.py loads the same modules).
_here = os.path.dirname(os.path.abspath(__file__))
_repo = os.path.dirname(_here)
sys.path.insert(0, _repo)

from tests.e2e.lib.tester_identity import (  # noqa: E402
    TesterIdentity,
    provision_tester,
    teardown_tester,
    AuthentikAdminError,
)
from tests.e2e.lib.wing_token_admin import WingToken  # noqa: E402


def _identity_to_payload(identity: TesterIdentity) -> dict:
    return {
        "username":        identity.username,
        "password":        identity.password,
        "email":           identity.email,
        "tier":            identity.tier,
        "group_name":      identity.group_name,
        "user_pk":         identity.user_pk,
        "group_pk":        identity.group_pk,
        "token_name":      identity.wing_token.name,
        "token_plaintext": identity.wing_token.plaintext,
    }


def _payload_to_identity(payload: dict) -> TesterIdentity:
    """Rehydrate just enough TesterIdentity for teardown_tester() to work.

    teardown_tester only reads: user_pk, group_pk, username, tier (for logs)
    and wing_token.name. Anything else can be ``""``/0 placeholders.
    """
    required = ("user_pk", "group_pk", "username", "token_name")
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"identity JSON missing required keys: {missing}")
    return TesterIdentity(
        username=payload["username"],
        password=payload.get("password", ""),
        email=payload.get("email", ""),
        tier=payload.get("tier", "user"),
        group_name=payload.get("group_name", ""),
        user_pk=int(payload["user_pk"]),
        group_pk=payload["group_pk"],
        wing_token=WingToken(
            name=payload["token_name"],
            plaintext=payload.get("token_plaintext", ""),
        ),
    )


def cmd_provision(args: argparse.Namespace) -> int:
    try:
        identity = provision_tester(args.tier)
    except (AuthentikAdminError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = _identity_to_payload(identity)
    if args.output == "-":
        json.dump(payload, sys.stdout)
        sys.stdout.write("\n")
    else:
        with open(args.output, "w") as fh:
            json.dump(payload, fh)
        print(f"Wrote {args.output}", file=sys.stderr)
    return 0


def cmd_teardown(args: argparse.Namespace) -> int:
    if args.input == "-":
        payload = json.load(sys.stdin)
    else:
        with open(args.input) as fh:
            payload = json.load(fh)

    try:
        identity = _payload_to_identity(payload)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # teardown_tester is best-effort: it logs but never raises. We still
    # exit 0 — the orphan-sweep is the safety net for partial failures.
    teardown_tester(identity)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_prov = sub.add_parser("provision", help="Create a fresh ephemeral tester")
    p_prov.add_argument("--tier", required=True,
                        choices=["provider", "manager", "user", "guest"])
    p_prov.add_argument("--output", default="-",
                        help="Output file (- for stdout, default)")
    p_prov.set_defaults(func=cmd_provision)

    p_down = sub.add_parser("teardown", help="Delete a previously-provisioned tester")
    p_down.add_argument("--input", default="-",
                        help="Input file with provision JSON (- for stdin, default)")
    p_down.set_defaults(func=cmd_teardown)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
