"""Anatomy gates for the Users + Invitations console (Anatomy A15, 2026-05-17).

Pins the structural contract for the multi-tenant invite flow so the SSO
audit chain stays single-spelling across:

  * wing.db schema       — user_invitations table shape
  * Wing PHP code        — AuthentikClient + UserInvitationRepository +
                            UsersPresenter (DI wiring, gates, methods)
  * Latte templates      — four views (default / invite / created /
                            invitations) plus a Tier-1-gated Users tab
                            in @layout.latte
  * Authentik blueprint  — 40-enrollment-flow.yaml.j2 ships every
                            required stage + the assign-target-groups
                            expression policy
  * Event-type whitelists — both Wing PHP VALID_TYPES + Bone Python
                            VALID_TYPES carry the new event types

These gates are intentionally structural rather than behavioural — a
behavioural E2E for invitation→redemption requires an actual Authentik
instance and lives under tests/e2e/. The gates here pin the contracts
that, when respected, give the E2E something to test against.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
WING = REPO / "files/anatomy/wing"
PLUGIN = REPO / "files/anatomy/plugins/authentik-base"


# ── Schema ────────────────────────────────────────────────────────────────


def test_user_invitations_table_declared():
    """user_invitations table must declare all audit-trail columns we
    surface in /users/invitations + the A10 actor_id backbone."""
    sql = (WING / "db/schema-extensions.sql").read_text()
    start = sql.find("CREATE TABLE IF NOT EXISTS user_invitations")
    assert start >= 0, "user_invitations table missing from schema-extensions.sql"
    end = sql.find(");", start)
    block = sql[start:end]
    required_columns = (
        "uuid", "invitation_pk", "invitation_url",
        "email_hint", "name_hint", "tenant",
        "target_groups_json", "target_apps_json",
        "expires_at", "single_use",
        "redeemed_at", "redeemed_user_pk", "revoked_at",
        "actor_id", "actor_action_id",
        "metadata_json", "created_at",
    )
    missing = [c for c in required_columns if c not in block]
    assert not missing, f"user_invitations missing columns: {missing}"


def test_user_invitations_indexes_present():
    sql = (WING / "db/schema-extensions.sql").read_text()
    for idx in (
        "idx_user_inv_actor",
        "idx_user_inv_tenant",
        "idx_user_inv_expires",
        "idx_user_inv_redeemed",
        "idx_user_inv_created",
    ):
        assert idx in sql, f"missing index {idx}"


# ── AuthentikClient ──────────────────────────────────────────────────────


def test_authentik_client_uses_bootstrap_token_env():
    """AUTHENTIK_BOOTSTRAP_TOKEN is the canonical env var (mirrors
    operator's ~/.nos/secrets.yml::authentik_bootstrap_token). Pinned
    here so a rename doesn't silently break the /users page."""
    src = (WING / "app/Model/AuthentikClient.php").read_text()
    assert "AUTHENTIK_BOOTSTRAP_TOKEN" in src
    assert "AUTHENTIK_DOMAIN" in src


def test_authentik_client_exposes_required_methods():
    """The presenter relies on a specific surface; any rename must come
    with a fixture update — this gate catches accidental drift."""
    src = (WING / "app/Model/AuthentikClient.php").read_text()
    for method in (
        "isConfigured",
        "listUsers",
        "listGroups",
        "listApplications",
        "listEnrollmentFlows",
        "findUserByPk",
        "createInvitation",
        "deleteInvitation",
        "listInvitations",
        "buildInvitationUrl",
    ):
        assert f"function {method}" in src, f"AuthentikClient::{method} missing"


def test_authentik_client_paginates_lists():
    """All list* helpers go through `paginate()` so a multi-page Authentik
    response doesn't get truncated at 100 rows. Caught a silent-truncate
    bug in the prototype draft."""
    src = (WING / "app/Model/AuthentikClient.php").read_text()
    # Each list method body should reference paginate().
    for method in ("listUsers", "listGroups", "listApplications", "listEnrollmentFlows", "listInvitations"):
        # Find the method body
        m = re.search(rf"function {method}\b[^{{]*\{{(.*?)\n\t\}}", src, re.DOTALL)
        assert m, f"{method} not parseable"
        assert "paginate" in m.group(1), f"{method} doesn't call paginate()"


# ── UserInvitationRepository ─────────────────────────────────────────────


def test_user_invitation_repository_required_methods():
    src = (WING / "app/Model/UserInvitationRepository.php").read_text()
    for method in ("insert", "listAll", "findByInvitationPk", "findByUuid", "countPending", "markRedeemed", "markRevoked"):
        assert f"function {method}" in src, f"UserInvitationRepository::{method} missing"


def test_user_invitation_repository_rejects_missing_required_fields():
    """The insert() guard must fail closed when caller forgets a required
    field (regression test was found in the draft — the early version
    silently inserted NULL invitation_url which broke the /users/created
    redirect on the first live test)."""
    src = (WING / "app/Model/UserInvitationRepository.php").read_text()
    assert "invitation_pk" in src and "invitation_url" in src and "expires_at" in src and "actor_id" in src
    assert "InvalidArgumentException" in src


# ── UsersPresenter ───────────────────────────────────────────────────────


def test_users_presenter_gated_by_super_admin():
    """Every render/action must pass through requireSuperAdmin(). The
    startup() method covers the whole presenter; sister checks pin the
    POST-action gate on top of that."""
    src = (WING / "app/Presenters/UsersPresenter.php").read_text()
    assert "requireSuperAdmin" in src
    assert "extends BasePresenter" in src
    # The startup() override must call requireSuperAdmin().
    assert re.search(r"function startup\b[^{]*\{[^}]*requireSuperAdmin", src, re.DOTALL), \
        "UsersPresenter::startup must call requireSuperAdmin"


def test_users_presenter_post_actions_require_post_method():
    """actionInviteCreate + actionRevoke must guard against GET so a
    phishing image src doesn't mint or revoke invitations."""
    src = (WING / "app/Presenters/UsersPresenter.php").read_text()
    for action_pattern in (
        r"function actionInviteCreate\b[^{]*\{[^}]*requirePostMethod",
        r"function actionRevoke\b[^{]*\{[^}]*requirePostMethod",
    ):
        assert re.search(action_pattern, src, re.DOTALL), \
            f"missing requirePostMethod guard matching {action_pattern}"


def test_users_presenter_tier_whitelist_complete():
    """The form-side tier whitelist must match the 4 canonical RBAC
    groups. Drift here silently lets the operator mint an invitation
    binding to a non-existent group."""
    src = (WING / "app/Presenters/UsersPresenter.php").read_text()
    for g in ("nos-managers", "nos-users", "nos-guests", "nos-admins"):
        assert f"'{g}'" in src, f"tier {g} missing from presenter whitelist"


def test_users_presenter_tenant_slug_pattern():
    """Tenant slug must be validated against a strict regex (no shell
    metacharacters; bounds-checked). Caught a draft where the regex
    matched empty string."""
    src = (WING / "app/Presenters/UsersPresenter.php").read_text()
    assert "'/^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]?$/'" in src


def test_users_presenter_emits_audit_events():
    """Issue + revoke actions must write user_invitation_issued /
    user_invitation_revoked events so /audit reconstructs the lineage."""
    src = (WING / "app/Presenters/UsersPresenter.php").read_text()
    assert "user_invitation_issued" in src
    assert "user_invitation_revoked" in src


def test_users_presenter_actor_id_from_forward_auth_headers():
    """Actor attribution comes from the X-Authentik-Username forward-auth
    header — never from request body. Pins the same anti-pattern guard
    that test_no_body_supplied_attribution_anti_pattern enforces on the
    API presenters."""
    src = (WING / "app/Presenters/UsersPresenter.php").read_text()
    assert "X-Authentik-Username" in src
    assert "getActorId" in src
    # The presenter must not read $body['actor_id'] / $body['resolved_by'] / etc.
    for forbidden in ("$body['actor_id']", "$body['invited_by']", "$body['resolved_by']"):
        assert forbidden not in src, f"presenter reads {forbidden} — privilege-escalation anti-pattern"


# ── Latte templates ──────────────────────────────────────────────────────


def test_users_templates_present():
    tpl_dir = WING / "app/Templates/Users"
    for f in ("default.latte", "invite.latte", "created.latte", "invitations.latte"):
        assert (tpl_dir / f).is_file(), f"Users/{f} missing"


def test_invite_form_posts_to_invite_create():
    """The form action must use plink Users:inviteCreate so the Nette
    router resolves to actionInviteCreate (which carries the POST guard)
    rather than a hand-typed URL that could drift."""
    src = (WING / "app/Templates/Users/invite.latte").read_text()
    assert "{plink Users:inviteCreate}" in src
    assert 'method="post"' in src


def test_invitations_revoke_form_uses_post():
    src = (WING / "app/Templates/Users/invitations.latte").read_text()
    assert "{plink Users:revoke}" in src
    assert 'method="post"' in src


def test_layout_carries_users_nav_entry_gated():
    """The Users tab is Tier-1 only — the layout must wrap it in the
    isSuperAdmin gate so guests + tier-3 users can't see it."""
    src = (WING / "app/Templates/@layout.latte").read_text()
    # Find the Users nav <a> and ensure it's inside a $isSuperAdmin block.
    m = re.search(
        r"\{if \$isSuperAdmin\}[^{]*<a[^>]*href=\"/users\"[^>]*data-tab=\"users\"",
        src,
        re.DOTALL,
    )
    assert m, "Users tab not gated by $isSuperAdmin in @layout.latte"


# ── DI registration ──────────────────────────────────────────────────────


def test_di_registers_authentik_client_and_repository():
    """Both services must be registered in common.neon so Nette can
    inject them into UsersPresenter without manual bootstrap."""
    src = (WING / "app/config/common.neon").read_text()
    assert "App\\Model\\AuthentikClient" in src
    assert "App\\Model\\UserInvitationRepository" in src


# ── Authentik enrollment blueprint ───────────────────────────────────────


def test_enrollment_blueprint_present_and_complete():
    """The blueprint must declare every stage the presenter relies on
    (invitation, prompt, user_write, user_login) plus the
    assign-target-groups expression policy + the flow with slug
    nos-enrollment."""
    blueprint = PLUGIN / "blueprints/40-enrollment-flow.yaml.j2"
    assert blueprint.is_file(), "40-enrollment-flow.yaml.j2 missing"
    src = blueprint.read_text()
    for needle in (
        "slug: nos-enrollment",
        "designation: enrollment",
        "nos-invitation-stage",
        "nos-enrollment-prompts",
        "nos-enrollment-user-write",
        "nos-enrollment-user-login",
        "nos-assign-target-groups",
        "authentik_stages_invitation.invitationstage",
        "authentik_stages_user_write.userwritestage",
        "authentik_policies_expression.expressionpolicy",
    ):
        assert needle in src, f"enrollment blueprint missing: {needle}"


def test_enrollment_blueprint_assigns_target_groups_from_prompt_data():
    """The expression policy must read prompt_data.target_groups (this is
    where Authentik 2024.x merges invitation.fixed_data). The fallback
    path to context.invitation.fixed_data is also present so older
    Authentik builds don't drop the binding silently."""
    src = (PLUGIN / "blueprints/40-enrollment-flow.yaml.j2").read_text()
    assert 'prompt_data.get("target_groups")' in src
    assert 'fixed_data' in src
    assert 'user.ak_groups.add' in src


def test_enrollment_blueprint_invitation_stage_refuses_anonymous():
    """The flow must NOT continue when ?itoken= is missing — no anonymous
    signup. Catches a draft where continue_flow_without_invitation was
    accidentally set to true."""
    src = (PLUGIN / "blueprints/40-enrollment-flow.yaml.j2").read_text()
    assert "continue_flow_without_invitation: false" in src


# ── Event-type whitelists ────────────────────────────────────────────────


def test_wing_event_repo_carries_new_event_types():
    src = (WING / "app/Model/EventRepository.php").read_text()
    assert "user_invitation_issued" in src
    assert "user_invitation_revoked" in src


def test_bone_events_whitelist_aligned():
    """Wing PHP + Bone Python whitelists MUST agree — a Bone POST proxying
    the same event (e.g. future webhook-driven redemption) would 400
    otherwise."""
    src = (REPO / "files/anatomy/bone/events.py").read_text()
    assert '"user_invitation_issued"' in src
    assert '"user_invitation_revoked"' in src


# ── Env wiring ───────────────────────────────────────────────────────────


def test_wing_plist_propagates_bootstrap_token():
    """wing.plist.j2 must inject AUTHENTIK_BOOTSTRAP_TOKEN from the
    operator-provisioned ~/.nos/secrets.yml. Optional (defaults to '')
    so a fresh install doesn't fail the launchd boot."""
    src = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
    assert "AUTHENTIK_BOOTSTRAP_TOKEN" in src
    assert "authentik_bootstrap_token | default('')" in src


def test_wing_plist_propagates_tenant_slugs():
    """Extra-tenant slugs surface in the invite form's tenant <select>.
    Missing the env makes the form a single-option fixed dropdown."""
    src = (REPO / "roles/pazny.wing/templates/wing.plist.j2").read_text()
    assert "TENANT_SLUGS" in src
    assert "tenants_extra" in src


# ── Router wiring ────────────────────────────────────────────────────────


def test_router_factory_mounts_users_routes():
    """RouterFactory must mount all six /users routes — without them
    Nette returns 404 even when the presenter + templates are present.
    Surfaced live during the first browser smoke (2026-05-17): /users
    rendered 404 until the router was updated. Specific routes
    (verb forms) MUST come before the catch-all `users` route so the
    first-match-wins router hits POST handlers + parameterized views
    first."""
    src = (REPO / "files/anatomy/wing/app/Core/RouterFactory.php").read_text()
    required = [
        "'users/invite-create', 'Users:inviteCreate'",
        "'users/invite', 'Users:invite'",
        "'users/created', 'Users:created'",
        "'users/invitations', 'Users:invitations'",
        "'users/revoke', 'Users:revoke'",
        "'users', 'Users:default'",
    ]
    for needle in required:
        assert needle in src, f"RouterFactory missing route: {needle}"

    # First-match ordering — catch-all must come last.
    default_pos = src.find("'users', 'Users:default'")
    for verb in ("users/invite-create", "users/invite", "users/created",
                 "users/invitations", "users/revoke"):
        verb_pos = src.find(f"'{verb}'")
        assert verb_pos >= 0
        assert verb_pos < default_pos, (
            f"route '{verb}' declared AFTER the catch-all 'users' — "
            f"first-match-wins router will never reach it"
        )


# ── Tier-1 SSO doctrine alignment ────────────────────────────────────────


def test_presenter_aligns_with_super_admin_groups():
    """The presenter's startup() gate uses requireSuperAdmin(), which per
    test_sso_doctrine.py + BasePresenter accepts BOTH `nos-providers`
    AND `nos-admins`. The presenter must not narrow that — re-asserting
    `requireGroup('nos-providers')` instead would 403 every operator
    whose identity (e.g. akadmin) lives in nos-admins."""
    src = (WING / "app/Presenters/UsersPresenter.php").read_text()
    # Specifically: presenter relies on requireSuperAdmin, NOT on the
    # single-group helper.
    assert "requireSuperAdmin" in src
    assert "requireGroup('nos-providers')" not in src
