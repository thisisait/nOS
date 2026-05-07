"""Ephemeral SSO tester identity orchestrator (A13.6).

Doctrine — why ephemeral?
=========================

The static blueprint user ``nos-tester`` (see
``roles/pazny.authentik/templates/blueprints/00-admin-groups.yaml.j2``) is
member of EVERY RBAC tier group, so it cannot be used to assert "tier-2 user
gets 403 on /admin" or "tier-4 user can't access /pentest". For RBAC matrix
testing we need **per-tier identities** that are scoped to exactly one group.

Operator security ask (verbatim, 2026-05-07):
    "kritické, aby playwright testing probíhal s SSO authorizovaným,
     auditovaným nos-tester userem, který musí vždy existovat (optimálně
     při každém běhu smazat a vygenerovat test user acc s náhodným heslem
     a novými tokeny, abychom zabránili leaku)"

Rules this module enforces:
    1. Random username + random password + random Wing token per provision.
       No reuse across runs — if a leak happens, blast radius is one test.
    2. Username carries a stable prefix (``nos-tester-e2e-``) so orphan-sweep
       can find leftovers from crashed runs.
    3. Teardown is best-effort but logs everything — pytest finalizers are
       the primary path; atexit + nightly Pulse sweep are belt-and-suspenders.
    4. ``actor_id`` on Wing events from these tests carries the ephemeral
       username, NOT the static ``nos-tester``. This way the audit trail
       distinguishes synthetic test runs from manual smoke probes, and lets
       us grep for ``actor_id LIKE 'nos-tester-e2e-%'`` to delete telemetry
       at the end of a CI run if we ever want to.

Tier mapping (canonical, ties to ``default.config.yml`` ``authentik_default_groups``):

    tier name      Authentik group        access expectation
    ───────────────────────────────────────────────────────
    "provider"  →  nos-providers          Tier-1 super-admin (sees /admin)
    "manager"   →  nos-managers           Tier-2 manager
    "user"      →  nos-users              Tier-3 user
    "guest"     →  nos-guests             Tier-4 guest
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from dataclasses import dataclass, field

from .authentik_admin import AuthentikAdmin, AuthentikGroup, AuthentikUser, AuthentikAdminError
from .wing_token_admin import WingToken, mint_token, revoke_token


logger = logging.getLogger("nos.e2e.tester")


USERNAME_PREFIX = "nos-tester-e2e-"
WING_TOKEN_NAME_PREFIX = "tester:e2e:"

TIER_TO_GROUP = {
    "provider": "nos-providers",
    "manager":  "nos-managers",
    "user":     "nos-users",
    "guest":    "nos-guests",
}


@dataclass
class TesterIdentity:
    """One ephemeral test identity. Created at fixture setup, deleted on
    teardown. Carries everything a test needs: SSO creds + bearer token + the
    Authentik PKs needed for cleanup.
    """
    username: str
    password: str
    email: str
    tier: str
    group_name: str
    user_pk: int
    group_pk: str
    wing_token: WingToken
    created_at: float = field(default_factory=time.time)

    @property
    def authorization_header(self) -> dict[str, str]:
        """Convenience: ``Authorization: Bearer <plaintext>`` dict for requests."""
        return {"Authorization": f"Bearer {self.wing_token.plaintext}"}


def _random_username() -> str:
    return USERNAME_PREFIX + secrets.token_hex(4)


def _random_password() -> str:
    # 32 bytes urlsafe → 43 base64 chars; well above any policy threshold
    return secrets.token_urlsafe(32)


def provision_tester(tier: str,
                     admin: AuthentikAdmin | None = None) -> TesterIdentity:
    """Create one ephemeral SSO + Wing identity in the requested RBAC tier.

    Sequence (each is independently logged so a partial failure leaves
    breadcrumbs for orphan-sweep):
        1. Resolve Authentik group PK by name ``nos-<tier>s``.
        2. POST /core/users/ with random username + ``automated_test_account``
           attribute (audit-trail marker).
        3. POST /core/users/<pk>/set_password/.
        4. POST /core/groups/<pk>/add_user/.
        5. Mint Wing token via ``provision-token.php`` subprocess.

    Raises ``AuthentikAdminError`` on any Authentik-side failure;
    ``RuntimeError`` if the group doesn't exist or token mint fails.
    """
    if tier not in TIER_TO_GROUP:
        raise ValueError(
            f"unknown tier {tier!r}; valid: {sorted(TIER_TO_GROUP)}"
        )
    group_name = TIER_TO_GROUP[tier]

    if admin is None:
        admin = AuthentikAdmin.from_env()

    # Step 1: group PK
    group: AuthentikGroup | None = admin.get_group_by_name(group_name)
    if group is None:
        raise RuntimeError(
            f"Authentik group {group_name!r} not found — has the playbook "
            "applied 00-admin-groups.yaml.j2 blueprint?"
        )

    # Step 2: create user
    username = _random_username()
    password = _random_password()
    tenant = os.environ.get("NOS_HOST") or os.environ.get("TENANT_DOMAIN") or "dev.local"
    email = f"{username}@{tenant}"
    logger.info("provisioning ephemeral tester user=%s tier=%s group=%s",
                username, tier, group_name)
    user: AuthentikUser = admin.create_user(
        username=username,
        name=f"E2E Tester ({tier})",
        email=email,
        is_active=True,
        attributes={
            "automated_test_account": True,
            "ephemeral": True,
            "tier": tier,
            "purpose": "Playwright + pytest E2E journey (A13.6)",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    )

    # Step 3: password
    admin.set_user_password(user.pk, password)

    # Step 4: group membership
    admin.add_user_to_group(group.pk, user.pk)

    # Step 5: Wing token
    token_name = WING_TOKEN_NAME_PREFIX + username
    token = mint_token(token_name)

    return TesterIdentity(
        username=username,
        password=password,
        email=email,
        tier=tier,
        group_name=group_name,
        user_pk=user.pk,
        group_pk=group.pk,
        wing_token=token,
    )


def teardown_tester(identity: TesterIdentity,
                    admin: AuthentikAdmin | None = None) -> None:
    """Delete user from Authentik + revoke Wing token. Idempotent — safe to
    call twice (DELETE returns success on 404, token revoke is rowcount-based).

    Errors are logged but NOT raised: teardown failures shouldn't mask the
    underlying test result. The orphan-sweep CI gate will catch leftovers.
    """
    if admin is None:
        try:
            admin = AuthentikAdmin.from_env()
        except AuthentikAdminError as exc:
            logger.warning("teardown: cannot reach Authentik (%s); leaving "
                           "user %s for orphan-sweep", exc, identity.username)
            return

    # A13.6 superuser-DELETE-405 fix: Authentik refuses to delete users that
    # are (transitively) superusers. The ``nos-providers`` group has
    # ``is_superuser=true`` (per 00-admin-groups.yaml.j2), so any provider-
    # tier tester inherits superuser via group membership and a plain DELETE
    # returns 405. Workaround: REMOVE the user from the group first — that
    # strips the inherited superuser bit — then DELETE succeeds. Done
    # unconditionally for all tiers so the path is uniform; remove_user_from_group
    # is idempotent and tolerates 404 already.
    try:
        admin.remove_user_from_group(identity.group_pk, identity.user_pk)
    except AuthentikAdminError as exc:
        logger.warning("teardown: group-remove failed for %s (continuing): %s",
                       identity.username, exc)

    try:
        admin.delete_user(identity.user_pk)
        logger.info("teardown: deleted Authentik user pk=%d username=%s tier=%s",
                    identity.user_pk, identity.username, identity.tier)
    except AuthentikAdminError as exc:
        logger.warning("teardown: Authentik DELETE failed for %s: %s",
                       identity.username, exc)

    try:
        rows = revoke_token(identity.wing_token.name)
        logger.info("teardown: revoked Wing token name=%s rows=%d",
                    identity.wing_token.name, rows)
    except Exception as exc:  # noqa: BLE001 — best effort
        logger.warning("teardown: Wing token revoke failed for %s: %s",
                       identity.wing_token.name, exc)


def sweep_orphans(max_age_seconds: int = 3600,
                  admin: AuthentikAdmin | None = None,
                  dry_run: bool = False) -> dict[str, int]:
    """Belt-and-suspenders: find every ``nos-tester-e2e-*`` user older than
    the threshold and delete them. Designed for:
      * pytest atexit hook (max_age=0 — kill everything we created)
      * nightly Pulse job (max_age=3600 — kill leaks from crashed runs)
      * anatomy CI gate (dry_run=True — assert count == 0)

    Returns ``{"found": N, "deleted": M, "skipped": K}``.
    """
    if admin is None:
        admin = AuthentikAdmin.from_env()

    now = time.time()
    found = 0
    deleted = 0
    skipped = 0

    for user in admin.list_users_by_prefix(USERNAME_PREFIX):
        # ── HARD SAFETY CHECK ─────────────────────────────────────────
        # A13.6 incident (2026-05-07): a single layer of prefix filtering
        # was bypassed by Authentik silently ignoring ``username__startswith``,
        # which led to 8 user deletions including the static blueprint user
        # ``nos-tester``. After that incident we ALSO verify the username
        # at the call site here — three independent checks (server filter,
        # list_users_by_prefix client filter, this final assertion) before
        # we touch DELETE. If ANY of them break, the others still hold.
        if not user.username.startswith(USERNAME_PREFIX):
            logger.error(
                "orphan-sweep: REFUSING to delete user=%s — does not match "
                "ephemeral prefix %r. This is a safety boundary; see A13.6 "
                "incident docstring for context.",
                user.username, USERNAME_PREFIX,
            )
            continue
        # Belt #4: even if the prefix check is somehow bypassed, never
        # delete is_superuser users. akadmin is_superuser=True; the static
        # ``nos-tester`` is not a superuser, so this only covers the
        # admin-account case but it's cheap insurance.
        if user.raw.get("is_superuser"):
            logger.error(
                "orphan-sweep: REFUSING to delete superuser=%s",
                user.username,
            )
            continue

        found += 1
        # Authentik returns ``date_joined`` ISO-8601; parse loosely.
        date_joined = user.raw.get("date_joined") or ""
        try:
            # ``2026-05-07T18:24:11.000Z`` — strip Z, parse via fromisoformat
            normalized = date_joined.rstrip("Z").split(".")[0]
            ts = time.mktime(time.strptime(normalized, "%Y-%m-%dT%H:%M:%S"))
            age = now - ts
        except (ValueError, TypeError):
            age = max_age_seconds + 1  # unparseable → assume old

        if age < max_age_seconds:
            skipped += 1
            continue

        if dry_run:
            logger.info("orphan-sweep(dry): would delete user=%s age=%.0fs",
                        user.username, age)
            continue
        try:
            admin.delete_user(user.pk)
            # Best-effort matching Wing token cleanup (no admin handle to admin
            # group memberships needed — Authentik DELETE cascades, and the
            # Wing token name prefix lets us find the exact row).
            revoke_token(WING_TOKEN_NAME_PREFIX + user.username)
            deleted += 1
            logger.info("orphan-sweep: deleted user=%s age=%.0fs",
                        user.username, age)
        except Exception as exc:  # noqa: BLE001
            logger.warning("orphan-sweep: failed to delete %s: %s",
                           user.username, exc)

    return {"found": found, "deleted": deleted, "skipped": skipped}
