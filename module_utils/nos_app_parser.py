"""nos_app_parser — parser + validator for Tier-2 apps (`apps/<name>.yml`).

Tier-2 apps are Coolify-style templates: a single YAML file with `meta:`,
`gdpr:`, and `compose:` blocks. Onboarding cost is ~30 min once the
schema is internalised, vs the ~half-day cost of writing a full
`pazny.<service>` role for a Tier-1 app. The trade-off: Tier-2 apps
get stack-level integration only — host loopback, networks, nginx vhost
auto-derivation — but no bespoke post-start API calls, no OIDC
auto-provisioning, no DB-prep tasks.

GDPR: the parser is the gate. **A Tier-2 app cannot deploy without a
complete `gdpr:` block.** This module surfaces three deploy gates the
runner must consult before `docker compose up`:

- ``gate_tls_required``  — if the app processes ``end_users`` data, the
  vhost must terminate TLS. Reject deploy without ssl_cert_path.
- ``gate_sso_required``  — if ``legal_basis == "consent"``, Authentik
  SSO must be wired (proxy auth at minimum) so consent collection is
  auditable.
- ``gate_eu_residency``  — if ``transfers_outside_eu == false``, every
  compose service image must come from an EU-or-neutral registry
  (docker.io, ghcr.io, registry.gitlab.com, lscr.io, quay.io). Reject
  US-only registries (gcr.io, public.ecr.aws, mcr.microsoft.com).

The parser is plain Python so it's unit-testable without Ansible. The
runner role (``pazny.apps_runner``, lands D4) imports it via
``ansible.module_utils.nos_app_parser`` from a custom action plugin or
a small helper module.

Spec lives in ``state/schema/app.schema.json`` (D3 too). Worked example
in ``apps/_template.yml``.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import base64
import os
import re
import secrets
import string
import sys
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml  # PyYAML
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Errors

class AppParseError(ValueError):
    """Raised when an app manifest fails schema or gate validation.

    Carries ``app_name`` (from the file basename, even if parse failed
    before reading ``meta.name``) and a list of structured ``violations``
    so the runner can surface them all at once instead of one at a time.
    """

    def __init__(self, app_name: str, violations: List[str]):
        self.app_name = app_name
        self.violations = list(violations)
        msg = "App %r failed validation:\n  - %s" % (
            app_name, "\n  - ".join(self.violations),
        )
        super(AppParseError, self).__init__(msg)


# ---------------------------------------------------------------------------
# Schema constants — the contract operators write against

REQUIRED_TOP_LEVEL = ("meta", "gdpr", "compose")

REQUIRED_META = ("name", "version", "summary")

# `gdpr` block — every key REQUIRED. No defaults. The whole point is
# that operators have to think about each one before the app deploys.
REQUIRED_GDPR = (
    "purpose",                # plain-language sentence: why we process
    "legal_basis",            # GDPR Art 6(1) — see GDPR_LEGAL_BASES
    "data_categories",        # list — which categories of personal data
    "data_subjects",          # list — whose data: end_users / employees / partners
    "retention_days",         # int — auto-erasure horizon, 0 = forever (REJECT in gate)
    "processors",             # list — third-party processors. [] OK, but explicit.
    "transfers_outside_eu",   # bool — drives gate_eu_residency
)

GDPR_LEGAL_BASES = (
    "consent",                # Art 6(1)(a) — opt-in, withdrawable
    "contract",               # Art 6(1)(b) — necessary to deliver service
    "legal_obligation",       # Art 6(1)(c) — required by law
    "vital_interests",        # Art 6(1)(d) — life-or-death
    "public_task",            # Art 6(1)(e) — public interest
    "legitimate_interests",   # Art 6(1)(f) — balancing test
)

# Data subject categories that flip ``gate_tls_required`` ON.
SENSITIVE_DATA_SUBJECTS = ("end_users", "patients", "minors", "employees")

# Image registries we consider EU-or-neutral. US-only registries get
# rejected when ``transfers_outside_eu: false``.
# (Trade-off: docker.io is US-headquartered but mirrors globally and
# is the de-facto registry; we treat it as neutral. Strict operators
# can override the allow-list via ``app_eu_registries`` group var.)
DEFAULT_EU_REGISTRIES = (
    "docker.io",
    "ghcr.io",
    "registry.gitlab.com",
    "lscr.io",          # linuxserver
    "quay.io",
    "registry.k8s.io",  # mirrored, OK
)

US_ONLY_REGISTRIES = (
    "gcr.io",
    "public.ecr.aws",
    "mcr.microsoft.com",
    "us-docker.pkg.dev",
)


# ---------------------------------------------------------------------------
# Loader

def load_app_file(path: str) -> Dict[str, Any]:
    """Read a YAML app manifest, return the parsed dict.

    Raises ``AppParseError`` on YAML parse failure. Does NOT validate
    the schema — call ``validate(record)`` after.
    """
    if yaml is None:
        # Surface the offending interpreter so the operator knows where
        # to install pyyaml. Ansible's auto-discovered interpreter on
        # macOS is /opt/homebrew/bin/python3, which Homebrew's python@3.13
        # upgrades occasionally strip pyyaml from. The pazny.apps_runner
        # role's main.yml ensures pyyaml is present before invoking the
        # render module — this branch is the safety net for callers
        # importing the parser directly.
        raise RuntimeError(
            "PyYAML required for nos_app_parser. Install with: "
            + sys.executable + " -m pip install --user --break-system-packages pyyaml"
        )
    app_name = os.path.splitext(os.path.basename(path))[0]
    try:
        with open(path, "r") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise AppParseError(app_name, ["YAML parse error: %s" % exc])
    if not isinstance(data, dict):
        raise AppParseError(app_name, ["top-level must be a mapping"])
    return data


# ---------------------------------------------------------------------------
# Schema validation — pure structural checks

def validate(record: Dict[str, Any], app_name: Optional[str] = None) -> None:
    """Validate an app record against the Tier-2 schema.

    Raises ``AppParseError`` accumulating ALL violations found. Caller
    sees every issue at once, not the first.

    The mandatory-`gdpr:`-block check is the highest-priority validation:
    if `gdpr:` is missing the parser refuses to look at anything else.
    """
    name = app_name or (record.get("meta", {}) or {}).get("name") or "<unknown>"
    violations: List[str] = []

    # ── 1. Top-level shape ──────────────────────────────────────────────
    for key in REQUIRED_TOP_LEVEL:
        if key not in record:
            violations.append("missing top-level key %r" % key)

    # GDPR check is the PRIMARY entry gate. If the block isn't there,
    # bail immediately — a runner that ignored other violations and
    # still deployed would create unregistered processing activity, a
    # GDPR Art 30 breach.
    if "gdpr" not in record:
        raise AppParseError(name, [
            "MANDATORY `gdpr:` block missing — Tier-2 apps cannot deploy "
            "without a complete GDPR Article 30 record. See "
            "apps/_template.yml for the required keys."
        ] + violations)

    # ── 2. meta block ───────────────────────────────────────────────────
    meta = record.get("meta") or {}
    if not isinstance(meta, dict):
        violations.append("`meta` must be a mapping")
    else:
        for key in REQUIRED_META:
            if not meta.get(key):
                violations.append("meta.%s is required and non-empty" % key)
        if "name" in meta and not _is_valid_app_name(meta["name"]):
            violations.append(
                "meta.name %r must match [a-z][a-z0-9-]*" % meta.get("name")
            )

    # ── 3. gdpr block — every key required ──────────────────────────────
    gdpr = record.get("gdpr") or {}
    if not isinstance(gdpr, dict):
        violations.append("`gdpr` must be a mapping")
    else:
        for key in REQUIRED_GDPR:
            if key not in gdpr:
                violations.append("gdpr.%s is required" % key)

        # Legal basis enum
        lb = gdpr.get("legal_basis")
        if lb is not None and lb not in GDPR_LEGAL_BASES:
            violations.append(
                "gdpr.legal_basis %r not in %s" % (lb, list(GDPR_LEGAL_BASES))
            )

        # Retention semantics: 0 means "forever", which is a GDPR Art 5(1)(e)
        # red flag (storage limitation). Operators that genuinely need
        # forever retention must opt out explicitly via retention_days: -1.
        rd = gdpr.get("retention_days")
        if rd is not None:
            if not isinstance(rd, int) or isinstance(rd, bool):
                violations.append("gdpr.retention_days must be an integer")
            elif rd == 0:
                violations.append(
                    "gdpr.retention_days: 0 is invalid — use a positive "
                    "integer for auto-erasure, or -1 to opt out explicitly"
                )

        # Type checks for list keys
        for list_key in ("data_categories", "data_subjects", "processors"):
            v = gdpr.get(list_key)
            if v is not None and not isinstance(v, list):
                violations.append("gdpr.%s must be a list" % list_key)

        # Type check for transfers_outside_eu
        teu = gdpr.get("transfers_outside_eu")
        if teu is not None and not isinstance(teu, bool):
            violations.append("gdpr.transfers_outside_eu must be a boolean")

    # ── 4. compose block — minimal structural check ─────────────────────
    compose = record.get("compose") or {}
    if not isinstance(compose, dict):
        violations.append("`compose` must be a mapping")
    elif "services" not in compose:
        violations.append("compose.services is required")
    elif not isinstance(compose["services"], dict) or not compose["services"]:
        violations.append("compose.services must be a non-empty mapping")

    if violations:
        raise AppParseError(name, violations)


# ---------------------------------------------------------------------------
# Deploy gates — consulted by the runner before `docker compose up`

def gate_tls_required(record: Dict[str, Any]) -> bool:
    """True if processing demands TLS termination (end_users etc.).

    Runner enforcement: when this returns True, the rendered nginx
    vhost MUST point at a real cert (no self-signed-only fallback).
    """
    subjects = (record.get("gdpr") or {}).get("data_subjects") or []
    return any(s in SENSITIVE_DATA_SUBJECTS for s in subjects)


def gate_sso_required(record: Dict[str, Any]) -> bool:
    """True if the app needs Authentik wiring (consent legal basis).

    Without auditable consent collection there's no Art 6(1)(a) basis
    to invoke. Authentik proxy auth at minimum; native OIDC if the app
    supports it.
    """
    return (record.get("gdpr") or {}).get("legal_basis") == "consent"


def gate_eu_residency(
    record: Dict[str, Any],
    extra_eu_registries: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    """Verify every compose image lives in an EU-or-neutral registry.

    Returns ``(ok, offending_images)``. Only enforced when
    ``gdpr.transfers_outside_eu == false``. If True, the parser
    short-circuits — operator has acknowledged the transfer.
    """
    gdpr = record.get("gdpr") or {}
    if gdpr.get("transfers_outside_eu") is True:
        return True, []  # explicitly acknowledged, parser is silent

    allowed = set(DEFAULT_EU_REGISTRIES)
    if extra_eu_registries:
        allowed.update(extra_eu_registries)

    services = ((record.get("compose") or {}).get("services") or {})
    offenders: List[str] = []
    for svc_name, svc in services.items():
        image = (svc or {}).get("image")
        if not image:
            continue  # build: directives are operator-built — assume OK
        registry = _split_registry(image)
        if registry in US_ONLY_REGISTRIES:
            offenders.append("%s -> %s (registry %s)" % (svc_name, image, registry))
        elif registry not in allowed:
            # Unknown explicit registry — flag for review. (Implicit
            # docker.io always matches `allowed`, so this only fires for
            # genuinely third-party hosts the operator named directly.)
            offenders.append("%s -> %s (registry %s, not in allow-list)" %
                             (svc_name, image, registry))
    return (not offenders), offenders


# ---------------------------------------------------------------------------
# Magic-token resolution (Coolify-style)
#
# Tier-2 templates use placeholders that the runner expands per-host. This
# keeps templates portable and readable — operators write
# ``$SERVICE_FQDN_IMMICH`` instead of `{{ instance_tld }}`. The expansion
# happens AFTER schema validation so a mistyped token is reported with
# the rendered text in scope, not the raw placeholder.
#
# Supported tokens:
#   $SERVICE_FQDN_<APP>          -> immich.<instance_tld>
#   $SERVICE_PASSWORD_<SUFFIX>   -> 32-char random, suffix groups same secret
#   $SERVICE_USER_<SUFFIX>       -> <app>_user (lowercase suffix)
#   $SERVICE_BASE64_64_<NAME>    -> 64-byte base64 (e.g. session keys)
#   $SERVICE_BASE64_32_<NAME>    -> 32-byte base64
#
# `_<SUFFIX>` groups identical credentials across services that share a
# DB, e.g. $SERVICE_PASSWORD_POSTGRES is the same value wherever it
# appears in the same template. This matches Coolify's behaviour.

_TOKEN_RE = re.compile(
    r"\$SERVICE_(FQDN|PASSWORD|USER|BASE64_64|BASE64_32)_([A-Z0-9_]+)"
)


def resolve_tokens(
    text: str,
    app_name: str,
    instance_tld: str,
    secret_seed: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[str, str]]:
    """Expand magic tokens in `text`. Returns (expanded, secrets_dict).

    ``secrets_dict`` exposes generated PASSWORD/BASE64 values so the
    runner can persist them to ``credentials.yml`` — without persistence
    every run regenerates and breaks the app's saved data.

    ``secret_seed`` lets the runner pre-seed values from a previous run
    so PASSWORD/BASE64 tokens stay stable across re-renders.
    """
    seed = dict(secret_seed or {})
    out_secrets: Dict[str, str] = {}

    def replace(match: re.Match) -> str:
        kind = match.group(1)
        suffix = match.group(2)
        cache_key = "%s_%s" % (kind, suffix)
        if cache_key in seed:
            value = seed[cache_key]
        elif kind == "FQDN":
            # APP suffix may include the app name itself (typical) or a
            # different subdomain like API. Lowercase it for the FQDN.
            value = "%s.%s" % (suffix.lower().replace("_", "-"), instance_tld)
        elif kind == "USER":
            value = "%s_%s" % (app_name, suffix.lower())
        elif kind == "PASSWORD":
            value = _random_password(32)
        elif kind == "BASE64_64":
            value = base64.b64encode(secrets.token_bytes(64)).decode("ascii")
        elif kind == "BASE64_32":
            value = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
        else:
            return match.group(0)
        # Cache so the same token reappearing in `text` resolves identically.
        seed[cache_key] = value
        # Only secrets get returned to the caller (FQDN/USER are derivable).
        if kind in ("PASSWORD", "BASE64_64", "BASE64_32"):
            out_secrets[cache_key] = value
        return value

    expanded = _TOKEN_RE.sub(replace, text)
    return expanded, out_secrets


# ---------------------------------------------------------------------------
# High-level convenience: parse + validate + gate-check in one call

def parse_app_file(path: str) -> Dict[str, Any]:
    """Load + validate. Returns the parsed record.

    Does NOT run the deploy gates — those need runner context (cert
    paths, Authentik URL, registry allow-list overrides). The runner
    calls them separately with that context in scope.
    """
    record = load_app_file(path)
    validate(record, app_name=os.path.splitext(os.path.basename(path))[0])
    return record


# ---------------------------------------------------------------------------
# Internal helpers

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _is_valid_app_name(name: Any) -> bool:
    return isinstance(name, str) and bool(_NAME_RE.match(name))


def _split_registry(image: str) -> str:
    """Return the registry host portion of an image reference.

    Docker reference grammar: a registry host is the first ``/``-separated
    component IF and only if it contains ``.``, ``:``, or is ``localhost``.
    Otherwise the first component is part of the path and the registry is
    implicit ``docker.io``.

      ``nginx:1.27``               -> docker.io  (no slash)
      ``library/nginx:1.27``       -> docker.io  (head has no . or :)
      ``ghcr.io/foo/bar:1``        -> ghcr.io
      ``localhost:5000/foo:1``     -> localhost:5000
    """
    if "/" not in image:
        return "docker.io"
    head = image.split("/", 1)[0]
    if "." in head or ":" in head or head == "localhost":
        return head
    return "docker.io"


def _random_password(n: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


# ---------------------------------------------------------------------------
# CLI smoke test:  python -m module_utils.nos_app_parser apps/<name>.yml

if __name__ == "__main__":  # pragma: no cover
    import json
    import sys

    if len(sys.argv) != 2:
        sys.stderr.write("usage: nos_app_parser.py <path-to-app.yml>\n")
        sys.exit(2)

    try:
        rec = parse_app_file(sys.argv[1])
    except AppParseError as exc:
        sys.stderr.write("FAIL: %s\n" % exc)
        sys.exit(1)
    except Exception as exc:
        sys.stderr.write("ERROR: %s\n" % exc)
        sys.exit(2)

    name = rec["meta"]["name"]
    print("OK: %s" % name)
    print("  TLS required:   %s" % gate_tls_required(rec))
    print("  SSO required:   %s" % gate_sso_required(rec))
    eu_ok, eu_offenders = gate_eu_residency(rec)
    print("  EU residency:   %s" % ("OK" if eu_ok else "VIOLATIONS"))
    for o in eu_offenders:
        print("    - %s" % o)
    print(json.dumps(rec.get("gdpr") or {}, indent=2, sort_keys=True))
