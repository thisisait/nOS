"""Anatomy CI gate — the playbook does not install a Redis it then disables.

MEASURED 2026-09-02: `brew services list` said `redis  none`. The package was in
homebrew_installed_packages unconditionally, and main.yml then stopped, unloaded
and deleted its LaunchAgent whenever redis_docker was true — which the
auto-enable list makes true on every realistic converge (Authentik alone).

The auto-enable list IS the consumer list, so redis_docker false means nothing
wanted Redis at all. Every redis-cli/redis-server reference in the tree is
in-container. The stop task stays for hosts provisioned before this.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_homebrew_does_not_install_redis():
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text(encoding="utf-8"))
    pkgs = cfg.get("homebrew_installed_packages") or []
    assert "redis" not in pkgs, (
        "homebrew_installed_packages carries `redis` again. The same converge "
        "stops and unloads it (main.yml, 'Stop Homebrew Redis if Docker Redis "
        "is enabled'), so it installs an orphan on every host. Redis runs in "
        "Docker; nothing on the host consumes the binaries")


def test_the_legacy_stop_survives():
    """Hosts provisioned before this still have the package and its LaunchAgent;
    dropping the stop would hand them a port conflict."""
    main = (REPO / "main.yml").read_text(encoding="utf-8")
    assert "Stop Homebrew Redis if Docker Redis is enabled" in main, (
        "the stop task is gone. Hosts that already have brew redis loaded would "
        "collide with infra-redis-1 on 6379")
