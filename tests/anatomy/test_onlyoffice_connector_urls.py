"""Anatomy CI gate — ONLYOFFICE / euro-office <-> Nextcloud connector wiring.

The browser loads the editor from the public DocumentServerUrl, but the two
servers also call EACH OTHER server-to-server. The playbook used to set ONLY
DocumentServerUrl, so the docserver tried to download files from localhost
(ECONNREFUSED) and `occ onlyoffice:documentserver --check` failed — the editor
would open but never load a document (audit 2026-06-13). This pins the
internal-URL wiring + the trusted-domain that makes the download callback work.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = (REPO / "roles/pazny.nextcloud/tasks/post.yml").read_text(encoding="utf-8")
DEFAULTS = (REPO / "roles/pazny.nextcloud/defaults/main.yml").read_text(encoding="utf-8")


def test_internal_urls_are_configured():
    # NC -> docserver and docserver -> NC, both over the shared docker net.
    assert "onlyoffice DocumentServerInternalUrl" in POST
    assert "onlyoffice StorageUrl" in POST
    assert "onlyoffice_internal_url" in POST and "nextcloud_internal_host" in POST


def test_internal_url_defaults_present():
    assert 'onlyoffice_internal_url: "http://onlyoffice/"' in DEFAULTS
    assert 'nextcloud_internal_host: "nextcloud"' in DEFAULTS


def test_internal_host_is_a_trusted_domain():
    # The docserver downloads via http://nextcloud/ ; NC 400s the Host as
    # untrusted unless it is a trusted_domain. It must sit at a fixed index
    # BELOW the dynamic extras (which now start at idx + 4, not idx + 3).
    assert 'index: 3, domain: "{{ nextcloud_internal_host' in POST
    assert "trusted_domains {{ idx + 4 }}" in POST
    assert "trusted_domains {{ idx + 3 }}" not in POST, \
        "extras must shift to idx+4 after the internal-host domain took index 3"


def test_euro_office_db_seed_is_blank_safe():
    # euro-office's image bakes its postgres cluster and won't initdb an empty
    # PGDATA, so a blank (which wipes onlyoffice_db_dir) would restart-loop the
    # container. The role must seed the cluster from the image when the dir is
    # fresh — gated to the euro-office image (the stock image self-initdbs).
    role = (REPO / "roles/pazny.onlyoffice/tasks/main.yml").read_text(encoding="utf-8")
    assert "Seed euro-office postgres cluster" in role
    assert "is search('euro-office')" in role, "seed must be euro-office-only"
    assert "_oo_db_contents.matched | default(0)) == 0" in role, \
        "seed must run only when the db dir is fresh/empty (idempotent)"
    assert "cp -a /var/lib/postgresql/. /seed-target/" in role
