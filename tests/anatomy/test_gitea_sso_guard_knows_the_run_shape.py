"""The Gitea lockout guard fires on a tag-restricted run, not on a full one.

Blank 2026-09-29: the guard in pazny.gitea/tasks/post.yml demanded the
Authentik OAuth source before tasks/stacks/authentik_service_post.yml — later
in the same play — had registered it, so every from-blank converge failed
there. The full run keeps its own loud verify in that file. This gate
evaluates the guard's `when` list the way Ansible does, for both run shapes.
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
POST = REPO / "roles/pazny.gitea/tasks/post.yml"
ASP = REPO / "tasks/stacks/authentik_service_post.yml"


def _guard() -> dict:
    tasks = yaml.safe_load(POST.read_text(encoding="utf-8"))
    return next(t for t in tasks if "refuse a hidden form" in t.get("name", ""))


def _fires(run_tags: list[str], auth_list: str) -> bool:
    env = jinja2.Environment()
    env.filters["bool"] = lambda v: str(v).lower() in ("1", "true", "yes")
    ctx = {
        "_gitea_container": {"stdout": "devops-gitea-1"},
        "install_authentik": True,
        "sso_autologin": True,
        "_gitea_idp_guard": {"stdout": auth_list},
        "ansible_run_tags": run_tags,
    }
    return all(env.from_string("{{ (" + w + ") | string }}").render(**ctx) == "True"
               for w in _guard()["when"])


def test_a_full_run_defers_to_the_service_side_verify() -> None:
    assert not _fires(["all"], "")


def test_a_tag_restricted_run_still_refuses_the_lockout() -> None:
    assert _fires(["gitea"], "")
    assert not _fires(["gitea"], "1  authentik  OAuth2")


def test_the_full_run_verify_is_loud() -> None:
    tasks = yaml.safe_load(ASP.read_text(encoding="utf-8"))
    verify = next(t for t in tasks if "Verify the Authentik OAuth2 source" in t.get("name", ""))
    assert "'authentik' not in" in verify["failed_when"]
