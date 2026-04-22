"""compose.set_image_tag — in-place rewrite of rendered overrides."""

from __future__ import absolute_import, division, print_function

import os

from module_utils.nos_upgrade_actions import compose_ops as co


OVERRIDE_TEMPLATE = """\
services:
  {svc}:
    image: {image}:{tag}
    container_name: nos-{svc}
    restart: unless-stopped
"""


def _write_override(base_ctx, stack, svc, image, tag):
    path = os.path.join(base_ctx["stacks_dir"], stack, "overrides",
                        "%s.yml" % svc)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(OVERRIDE_TEMPLATE.format(svc=svc, image=image, tag=tag))
    # Base compose must exist for the up --wait command path, but tests
    # don't actually invoke docker because wait=False.
    base = os.path.join(base_ctx["stacks_dir"], stack, "compose.yml")
    if not os.path.exists(base):
        with open(base, "w") as fh:
            fh.write("services: {}\n")
    return path


def test_set_image_tag_rewrites_in_place(base_ctx):
    path = _write_override(base_ctx, "observability", "grafana",
                           "grafana/grafana-oss", "11.5.0")
    res = co.handle_set_image_tag({
        "stack": "observability",
        "service": "grafana",
        "tag": "12.0.0",
        "wait": False,
    }, base_ctx)
    assert res["success"]
    assert res["changed"]
    with open(path) as fh:
        content = fh.read()
    assert "grafana/grafana-oss:12.0.0" in content
    assert "grafana/grafana-oss:11.5.0" not in content
    # Restart / other lines preserved.
    assert "restart: unless-stopped" in content
    assert "container_name: nos-grafana" in content


def test_set_image_tag_idempotent_when_already_set(base_ctx):
    _write_override(base_ctx, "infra", "redis", "redis", "8.0")
    res = co.handle_set_image_tag({
        "stack": "infra", "service": "redis", "tag": "8.0", "wait": False,
    }, base_ctx)
    assert res["success"]
    assert not res["changed"]


def test_set_image_tag_multi_service(base_ctx):
    _write_override(base_ctx, "infra", "authentik-server", "ghcr.io/goauthentik/server", "2024.12.3")
    _write_override(base_ctx, "infra", "authentik-worker", "ghcr.io/goauthentik/server", "2024.12.3")
    res = co.handle_set_image_tag({
        "stack": "infra",
        "services": ["authentik-server", "authentik-worker"],
        "tag": "2025.2.1",
        "wait": False,
    }, base_ctx)
    assert res["success"]
    assert res["changed"]
    for svc in ("authentik-server", "authentik-worker"):
        path = os.path.join(base_ctx["stacks_dir"], "infra", "overrides", "%s.yml" % svc)
        with open(path) as fh:
            body = fh.read()
        assert ":2025.2.1" in body
        assert "2024.12.3" not in body


def test_set_image_tag_missing_override_fails(base_ctx):
    res = co.handle_set_image_tag({
        "stack": "infra", "service": "nowhere", "tag": "1.0", "wait": False,
    }, base_ctx)
    assert not res["success"]


def test_restart_service_invokes_docker_compose(base_ctx, cmd_recorder):
    # Ensure compose.yml exists so the command list includes -f for it.
    stack_dir = os.path.join(base_ctx["stacks_dir"], "infra")
    os.makedirs(stack_dir, exist_ok=True)
    with open(os.path.join(stack_dir, "compose.yml"), "w") as fh:
        fh.write("services: {}\n")
    res = co.handle_restart_service({
        "stack": "infra", "service": "mariadb", "action": "restart",
    }, base_ctx)
    assert res["success"]
    assert cmd_recorder.calls, "expected docker compose invocation"
    called = cmd_recorder.calls[0]["cmd"]
    assert called[0] == "docker"
    assert "restart" in called and "mariadb" in called


def test_restart_service_up_wait(base_ctx, cmd_recorder):
    stack_dir = os.path.join(base_ctx["stacks_dir"], "infra")
    os.makedirs(stack_dir, exist_ok=True)
    with open(os.path.join(stack_dir, "compose.yml"), "w") as fh:
        fh.write("services: {}\n")
    co.handle_restart_service({
        "stack": "infra", "service": "postgresql", "action": "up", "wait": True,
    }, base_ctx)
    called = cmd_recorder.calls[0]["cmd"]
    assert "up" in called and "-d" in called and "--wait" in called
