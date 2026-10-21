"""The parser refuses a compose that breaks nOS's standards, one named reason each.

Measured 2026-10-21: a model-authored dtt-editor manifest (fixtures/dtt-editor.yml)
parsed rc 0 while publishing 8080 on 0.0.0.0, hand-writing traefik labels,
passing KEAP_AGENT_TOKEN_RW, bind-mounting ./apps/..., pinning nginx:alpine and
setting no limits. The model reads the reasons to fix the manifest, so each one
starts "standard <rule>:".
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from module_utils.nos_app_parser import AppParseError, load_app_file, validate

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "dtt-editor.yml"

GOOD = {
    "meta": {"name": "demo", "version": "1.0.0", "summary": "demo app", "ports": [8080]},
    "gdpr": {
        "purpose": "demo processing", "legal_basis": "contract",
        "data_categories": ["email"], "data_subjects": ["partners"],
        "retention_days": 90, "processors": [], "transfers_outside_eu": False,
    },
    "compose": {"services": {"demo": {
        "image": "ghcr.io/demo/app:1.0.0",
        "ports": ["127.0.0.1:8080:8080"],
        "environment": ["PW=$SERVICE_PASSWORD_DB", "URL=https://$SERVICE_FQDN_DEMO/",
                        "U=$SERVICE_USER_DB", "K=$SERVICE_BASE64_32_KEY"],
        "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]},
        "volumes": ["demo_data:/data", "/anon"],
        "networks": ["apps_net"],
        "mem_limit": "256m", "cpus": 0.5,
    }}, "volumes": {"demo_data": None}},
}


def _rules(record):
    try:
        validate(record)
    except AppParseError as exc:
        return {v.split(":", 1)[0].replace("standard ", "") for v in exc.violations
                if v.startswith("standard ")}
    return set()


def _with(**svc):
    rec = copy.deepcopy(GOOD)
    s = rec["compose"]["services"]["demo"]
    for k, v in svc.items():
        if v is None:
            s.pop(k, None)
        else:
            s[k] = v
    return rec


def test_the_good_record_passes():
    validate(copy.deepcopy(GOOD))


def test_the_mistral_manifest_is_refused_with_each_reason():
    # No network reason: it omits networks:, and the runner attaches apps_net.
    assert _rules(load_app_file(str(FIXTURE))) == {
        "floating-image-tag", "host-port-not-loopback", "host-port-not-in-meta-ports",
        "traefik-label", "platform-secret", "bind-mount", "no-resource-limits",
    }


@pytest.mark.parametrize("svc,rule", [
    ({"ports": ["8080:8080"]}, "host-port-not-loopback"),
    ({"ports": ["0.0.0.0:8080:8080"]}, "host-port-not-loopback"),
    ({"ports": ["[::]:8080:8080"]}, "host-port-not-loopback"),
    ({"ports": ["8080"]}, "host-port-not-loopback"),
    ({"ports": [{"target": 8080, "published": 8080}]}, "host-port-not-loopback"),
    ({"ports": ["127.0.0.1:9999:8080"]}, "host-port-not-in-meta-ports"),
    ({"labels": {"traefik.enable": "true"}}, "traefik-label"),
    ({"labels": ["traefik.http.routers.x.rule=Host(`x`)"]}, "traefik-label"),
    ({"environment": ["A=${HOME}"]}, "env-interpolation"),
    ({"environment": {"A": "$PATH"}}, "env-interpolation"),
    ({"environment": ["A=${SERVICE_PASSWORD_DB}"]}, "env-interpolation"),
    ({"command": ["sh", "-c", "echo $X"]}, "env-interpolation"),
    ({"environment": ["T=${KEAP_AGENT_TOKEN_RW}"]}, "platform-secret"),
    ({"environment": ["T=$WING_API_TOKEN"]}, "platform-secret"),
    ({"environment": ["T=${BONE_SECRET:-x}"]}, "platform-secret"),
    ({"environment": ["T=${GITEA_API_TOKEN}"]}, "platform-secret"),
    ({"volumes": ["./code:/srv"]}, "bind-mount"),
    ({"volumes": ["/etc:/etc:ro"]}, "bind-mount"),
    ({"volumes": ["~/x:/x"]}, "bind-mount"),
    ({"volumes": [{"type": "bind", "source": "data", "target": "/d"}]}, "bind-mount"),
    ({"volumes": ["/var/run/docker.sock:/var/run/docker.sock"]}, "docker-socket"),
    ({"image": "nginx"}, "floating-image-tag"),
    ({"image": "nginx:latest"}, "floating-image-tag"),
    ({"image": "nginx:alpine"}, "floating-image-tag"),
    ({"image": "python:3"}, "floating-image-tag"),
    ({"image": "postgres:15-alpine"}, "floating-image-tag"),
    ({"image": "localhost:5000/app"}, "floating-image-tag"),
    ({"networks": ["infra_net"]}, "network-not-apps-net"),
    ({"networks": ["apps_net", "gated_b2b_net"]}, "network-not-apps-net"),
    ({"networks": {"shared_net": {}}}, "network-not-apps-net"),
    ({"mem_limit": None}, "no-resource-limits"),
    ({"cpus": None}, "no-resource-limits"),
    ({"privileged": True}, "privileged"),
    ({"cap_add": ["NET_ADMIN"]}, "cap-add"),
    ({"cap_add": ["CHOWN"]}, "cap-add"),
    ({"cap_drop": ["ALL"], "cap_add": ["SYS_ADMIN"]}, "cap-add"),
    ({"network_mode": "host"}, "host-namespace"),
    ({"pid": "host"}, "host-namespace"),
])
def test_each_rule_refuses_by_name(svc, rule):
    assert _rules(_with(**svc)) == {rule}


@pytest.mark.parametrize("svc", [
    {"ports": None},
    {"ports": ["127.0.0.1:8080:8080/tcp"]},
    {"ports": [{"target": 8080, "published": 8080, "host_ip": "127.0.0.1"}]},
    {"image": "nginx@sha256:" + "a" * 64},
    {"image": "postgres:15.19-alpine"},
    {"image": "minio/minio:RELEASE.2025-04-22T22-12-26Z"},
    {"networks": None},
    {"networks": ["gated_net"]},
    {"networks": ["apps_net", "shared_net"]},
    {"mem_limit": None, "cpus": None, "deploy": {"resources": {"limits": {"memory": "1g", "cpus": "1"}}}},
    {"cap_drop": ["ALL"], "cap_add": ["CHOWN", "SETUID", "SETGID"]},
    {"volumes": [{"type": "volume", "source": "demo_data", "target": "/d"}, {"type": "tmpfs", "target": "/t"}]},
])
def test_what_the_standards_accept(svc):
    assert _rules(_with(**svc)) == set()


@pytest.mark.parametrize("manifest", sorted((REPO / "apps").glob("*.yml*")), ids=lambda p: p.name)
def test_every_committed_app_meets_the_standards(manifest):
    assert _rules(load_app_file(str(manifest))) == set()


def test_the_estate_check_names_a_taken_name_and_port():
    """--estate asks tools/app-slots.py; apps/documenso.yml holds the name and port 3000."""
    from module_utils.nos_app_parser import estate_violations
    rec = _with(ports=["127.0.0.1:3000:3000"])
    rec["meta"].update(name="documenso", ports=[3000])
    validate(rec)  # the plain parse is offline and passes
    got = estate_violations(rec, live=False)
    assert any(v.startswith("estate name-taken: 'documenso'") for v in got), got
    assert any(v.startswith("estate port-taken: services.demo host port 3000") for v in got), got
