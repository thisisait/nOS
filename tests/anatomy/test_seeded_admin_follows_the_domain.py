"""A seeded admin follows a tenant_domain change instead of being left behind.

Roles that seed an admin under admin@<tenant_domain> and look it up BY that
e-mail found nobody after a domain switch (spark1, 2026-10-19): a second admin
was minted, or the login was refused. Each lookup below is rendered with two
tenant domains; when the rendered lookup differs, the same file must carry a
step that moves the old account to the declared e-mail (needle = its verb).
"""
from __future__ import annotations

import pathlib
import shlex

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

# (file, lookup item name/id, move item name/id, needle the move must carry)
SEEDS = {
    "freescout": ("roles/pazny.freescout/tasks/post.yml", "Check if admin user exists",
                  "Move the admin to the declared email", "MOVED"),
    "freescout-hook": ("files/anatomy/plugins/freescout-base/hooks/post_compose.yml", "check_admin_exists",
                       "move_admin_email", "MOVED"),
    "metabase": ("roles/pazny.metabase/tasks/post.yml", "Login with current password",
                 "Move the admin to the declared email", "/api/user/"),
    "dolibarr": ("roles/pazny.dolibarr/tasks/post.yml", "Ensure the SSO admin user",
                 "Move the SSO admin to the declared login", "UPDATE llx_user"),
    "n8n": ("roles/pazny.n8n/tasks/post.yml", "Login with current password",
            "Move the owner to the declared email", "PATCH"),
    "open_webui": ("roles/pazny.open_webui/tasks/post.yml", "Ensure admin user",
                   "Ensure admin user", "MOVED"),
    # Keyed by username: the lookup must render the same under both domains.
    "gitea": ("roles/pazny.gitea/tasks/post.yml", "Does the declared admin password already log in", None, None),
    "superset": ("roles/pazny.superset/tasks/post.yml", "Reset the admin password", None, None),
    "wordpress": ("roles/pazny.wordpress/tasks/post.yml", "Reconverge admin password",
                  "Reconverge admin password", "--user_email"),
}
# Fixed on feat/linux-dgx-core (d7a8c34bb, 4b852b167); drop the mark once it lands.
DGX = {"n8n", "open_webui"}

ENV = jinja2.Environment(undefined=jinja2.ChainableUndefined)
ENV.filters.update(quote=lambda s: shlex.quote(str(s)), bool=bool, to_json=str)


def _vars(domain: str) -> dict:
    layers = [REPO / "default.config.yml", REPO / "roles/pazny.dolibarr/defaults/main.yml"]
    raw = {}
    for f in layers:
        raw.update({k: v for k, v in (yaml.safe_load(f.read_text()) or {}).items()
                    if isinstance(v, str) and ("email" in k or k.endswith("_login"))})
    ctx = {"tenant_domain": domain, **raw}
    for _ in range(3):  # resolve the e-mail chain (role → default_admin_email → tenant_domain)
        ctx = {k: (ENV.from_string(v).render(ctx) if isinstance(v, str) else v) for k, v in ctx.items()}
    return ctx


def _items(path: str) -> list[dict]:
    doc = yaml.safe_load((REPO / path).read_text())
    return doc["sequence"] if isinstance(doc, dict) else doc


def _render(node, ctx):
    if isinstance(node, dict):
        return {k: _render(v, ctx) for k, v in node.items()}
    if isinstance(node, list):
        return [_render(v, ctx) for v in node]
    return ENV.from_string(node).render(ctx) if isinstance(node, str) else node


def _find(items: list[dict], key: str) -> dict | None:
    return next((t for t in items if key in str(t.get("name", t.get("id", "")))), None)


@pytest.mark.parametrize("seed", [pytest.param(s, marks=pytest.mark.xfail(strict=True, reason="fix lives on feat/linux-dgx-core"))
                                  if s in DGX else s for s in SEEDS])
def test_the_seeded_admin_follows_the_domain(seed):
    path, lookup_key, move_key, needle = SEEDS[seed]
    items = _items(path)
    lookup = _find(items, lookup_key)
    assert lookup, f"{path}: no item named {lookup_key!r}"
    a, b = (_render(lookup, _vars(d)) for d in ("one.example", "two.example"))
    if a == b:
        return
    move = _find(items, move_key) if move_key else None
    assert move and needle in str(move), (
        f"{seed}: the admin lookup in {path} depends on tenant_domain and nothing moves the old "
        f"account to the declared e-mail — a domain change mints a second admin or refuses the login")
