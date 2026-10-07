"""Anatomy gate — PostGIS rides the pinned postgres, on every arch, and is created idempotently.

2026-10-03: the planned swap was `imresamu/postgis:16-3.5.3-alpine3.22`, a
multi-arch tag that looked like "same PG major". Measured per platform it carried
PG 16.10, and its fresher siblings carry 16.11 on amd64 vs 16.15 on arm64 — a
silent CVE regression below the `postgresql_version` floor on Ubuntu hosts.
So PostGIS is compiled onto `postgres:{{ postgresql_version }}` per host:

  1. with install_postgis the service builds FROM exactly the pinned postgres,
     the tag names both versions, and the source tarball is sha256-checked;
  2. without it the image is the plain pinned postgres (nothing changes);
  3. the geo database is created in the DB loop and PostGIS + schema geo with
     IF NOT EXISTS, ON_ERROR_STOP and no `failed_when: false`.
"""
from __future__ import annotations

import sys
import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402
ROLE = REPO / "roles/pazny.postgresql"
DOCKERFILE = REPO / "files/postgis/Dockerfile"
CONFIG = ni.default_config()


def _service(install_postgis: bool) -> dict:
    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    text = env.from_string((ROLE / "templates/compose.yml.j2").read_text()).render(
        install_postgis=install_postgis, postgresql_version=CONFIG["postgresql_version"],
        postgis_version=CONFIG["postgis_version"], postgis_sha256=CONFIG["postgis_sha256"],
        nos_main_checkout="/repo", stacks_shared_network="shared", docker_mem_limit_standard="1g",
        ansible_facts={"env": {"HOME": "/h"}}, nos_derived_secrets={"postgresql": "x"})
    return yaml.safe_load(text)["services"]["postgresql"]


def test_postgis_builds_from_the_pinned_postgres():
    svc = _service(True)
    assert "build" in svc, "PostGIS must be built per host — a prebuilt multi-arch tag lagged the PG pin"
    assert svc["build"]["context"].endswith("/files/postgis")
    assert svc["build"]["args"]["BASE"] == f"postgres:{CONFIG['postgresql_version']}"
    assert svc["image"] == f"nos/postgis:{CONFIG['postgresql_version']}-{CONFIG['postgis_version']}"
    assert re.fullmatch(r"[0-9a-f]{64}", CONFIG["postgis_sha256"])


def test_without_postgis_the_image_is_the_pin():
    assert _service(False)["image"] == f"postgres:{CONFIG['postgresql_version']}"


def test_dockerfile_checks_the_source_and_has_no_second_pin():
    text = DOCKERFILE.read_text()
    assert re.search(r"^FROM \$\{BASE\}$", text, re.M)
    assert "sha256sum -c" in text, "the PostGIS tarball must be verified"
    assert re.search(r"^ARG POSTGIS_VERSION$", text, re.M) and re.search(r"^ARG POSTGIS_SHA256$", text, re.M), (
        "postgis_version lives in default.config.yml only — a Dockerfile default is a second pin")


def test_geo_database_and_extension_are_idempotent_and_loud():
    tasks = yaml.safe_load((ROLE / "tasks/post.yml").read_text())
    create = next(t for t in tasks if t["name"] == "[PostgreSQL] Create databases")
    assert "geo_db_name" in create["loop"]
    task = next(t for t in tasks if "PostGIS" in t["name"])
    cmd = task["ansible.builtin.command"]
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in cmd and "CREATE SCHEMA IF NOT EXISTS geo" in cmd
    assert "ON_ERROR_STOP=1" in cmd
    assert "failed_when" not in task, "a PostGIS that cannot be created must fail the play"
    assert "install_postgis | default(false)" in task["when"]
