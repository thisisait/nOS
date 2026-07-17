"""Provisioning-time OIDC discovery must be reachable from the service container.

CLASS-RISK (surfaced live 2026-07-17, ok=1262):
    A `native_oidc` service whose OIDC client is REGISTERED by a
    *provisioning-time server-side discovery fetch* — an Ansible task that
    `docker compose exec`s a CLI *inside the service container* which then
    fetches `https://auth.<tld>/application/o/<svc>/.well-known/openid-configuration`
    SYNCHRONOUSLY during the playbook run — will silently fail if the container
    can't resolve `auth.<tld>`. Docker's embedded DNS (127.0.0.11) can't resolve
    the public/local TLD, so the fetch dies with "server misbehaving". Because
    these registration tasks run `failed_when: false`, the run stays green while
    SSO is dead.

    The fix is an `extra_hosts` alias mapping `auth.<tld>` → `host-gateway`
    (Traefik :443 on the host), gated behind `install_authentik`. Nextcloud-base
    already had it; Gitea LACKED it (add-oauth failed silently) and it was added
    2026-07-17. This gate pins BOTH so a future provisioning-time-discovery
    service can't regress.

Criterion for membership in PROVISIONING_DISCOVERY_SERVICES below:
    The service's OIDC client/source is created by an Ansible task that runs a
    command INSIDE the container (`docker compose ... exec`) which performs the
    discovery fetch itself, at provisioning time. Proven cases:
      - gitea    : `gitea admin auth add-oauth --auto-discover-url <well-known>`
                   (tasks/stacks/authentik_service_post.yml)
      - nextcloud: `occ user_oidc:provider ... --discoveryuri=<well-known>`
                   (tasks/stacks/authentik_service_post.yml)
    NOT in scope (deliberately): services that hand OIDC config to the container
    via env/DB and let the container fetch discovery LAZILY at login runtime
    (freescout, paperclip-probe, homeassistant, superset, infisical, erpnext).
    Those still need the alias for RUNTIME OIDC, but that's a different failure
    mode (login-time, not silent provisioning); add them here only if a future
    change makes their client REGISTRATION a synchronous provisioning fetch.

Offline / text-based by design: these are Jinja2 templates that can't be
rendered without the full var stack, so we assert the literal
`{{ authentik_domain ... }}:host-gateway` extra_host mapping is present AND sits
inside an `{% if install_authentik ... %}` guard.
"""
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

# service -> candidate rendered-compose sources (role compose AND/OR plugin
# compose-extension). The alias may live in EITHER; we require it in >=1.
PROVISIONING_DISCOVERY_SERVICES = {
    "gitea": [
        "roles/pazny.gitea/templates/compose.yml.j2",
        "files/anatomy/plugins/gitea-base/templates/gitea-base.compose.yml.j2",
    ],
    "nextcloud": [
        "roles/pazny.nextcloud/templates/compose.yml.j2",
        "files/anatomy/plugins/nextcloud-base/templates/nextcloud-base.compose.yml.j2",
    ],
}

# An extra_host mapping line that points the auth domain at the host gateway.
# Matches:  - "{{ authentik_domain | default('auth' ~ ... ~ tenant_domain) }}:host-gateway"
# Accepts either a direct `authentik_domain` reference OR the
# `'auth' ~ ... ~ tenant_domain` expansion (the spec's OR), on the SAME line as
# `:host-gateway`.
_HOST_GATEWAY = ":host-gateway"


def _line_has_auth_hostgateway(line):
    if _HOST_GATEWAY not in line:
        return False
    if "authentik_domain" in line:
        return True
    # expansion form: 'auth' ... tenant_domain, all on one line
    return "tenant_domain" in line and "auth" in line


def _guard_stack_at(lines, idx):
    """Return the stack of `{% if %}` conditions enclosing line `idx`.

    Walks top->idx maintaining a stack: push on `{% if %}`, pop on `{% endif %}`.
    `{% elif %}`/`{% else %}` are not used on these guards, so they're ignored.
    """
    stack = []
    if_re = re.compile(r"{%-?\s*if\s+(.+?)\s*-?%}")
    endif_re = re.compile(r"{%-?\s*endif\s*-?%}")
    for i in range(idx):
        line = lines[i]
        m = if_re.search(line)
        if m:
            stack.append(m.group(1))
        elif endif_re.search(line):
            if stack:
                stack.pop()
    return stack


def _find_guarded_alias(text):
    """(found_line, guarded_by_install_authentik) for the auth host-gateway alias."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if _line_has_auth_hostgateway(line):
            guards = _guard_stack_at(lines, idx)
            guarded = any("install_authentik" in g for g in guards)
            return line.strip(), guarded
    return None, False


def test_provisioning_discovery_services_have_auth_host_gateway():
    """Each provisioning-time-discovery service maps auth.<tld> → host-gateway,
    gated behind install_authentik, in its role compose or plugin compose-ext."""
    failures = []
    for svc, candidates in sorted(PROVISIONING_DISCOVERY_SERVICES.items()):
        existing = [(c, (ROOT / c)) for c in candidates if (ROOT / c).exists()]
        if not existing:
            failures.append(f"{svc}: NONE of its candidate compose sources exist: {candidates}")
            continue

        found_anywhere = False
        guarded_anywhere = False
        seen = []
        for rel, path in existing:
            line, guarded = _find_guarded_alias(path.read_text())
            if line is not None:
                seen.append(f"{rel}: {line!r} (install_authentik-guarded={guarded})")
                found_anywhere = True
                guarded_anywhere = guarded_anywhere or guarded

        if not found_anywhere:
            failures.append(
                f"{svc}: NO `{{{{ authentik_domain ... }}}}:host-gateway` extra_host in any of "
                f"{[r for r, _ in existing]} — a provisioning-time discovery fetch inside the "
                f"container will fail to resolve auth.<tld> (silent SSO death)."
            )
        elif not guarded_anywhere:
            failures.append(
                f"{svc}: found the host-gateway alias but it is NOT inside an "
                f"`{{% if install_authentik ... %}}` guard:\n    " + "\n    ".join(seen)
            )

    assert not failures, (
        "native_oidc provisioning-time discovery reachability broken:\n"
        + "\n".join(failures)
    )
