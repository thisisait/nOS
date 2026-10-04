"""Only a socket proxy may mount the Docker socket.

docker.sock is root on the host, and `:ro` on a unix socket is cosmetic — the
API is a protocol, not a file. Watchtower (rw), the Woodpecker agent and
cAdvisor (via /var/run) mounted it directly while Traefik and Portainer went
through tecnativa/docker-socket-proxy. Each consumer now has its own proxy
instance carrying only the API sections it needs (workload-allowlist epic).

The gate RENDERS every compose template (every install_* on, Darwin and
Linux) and parses the YAML: a bind whose source is docker.sock, or a directory
that contains it, is allowed only on a socket-proxy service. A template that
that does not render is red, not skipped.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import jinja2
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PROXY_IMAGE = "tecnativa/docker-socket-proxy"
#: Directories a bind can expose the socket through (Linux: /var/run -> /run).
SOCKET_DIRS = {"/", "/var", "/var/run", "/run"}
#: Declared exceptions: (service, source) -> reason.
EXCEPTIONS = {
    ("cadvisor", "/"): "privileged, Linux-only; needs host / at /rootfs for fs "
                       "stats — root on host by privileged:true regardless",
}

TEMPLATES = sorted(
    [*REPO.glob("roles/pazny.*/templates/*compose*.j2"),
     *REPO.glob("templates/stacks/*/docker-compose.yml.j2"),
     *REPO.glob("files/anatomy/plugins/*/templates/*compose*.j2"),
     *REPO.glob("apps/*.yml")])


class _Lenient(jinja2.ChainableUndefined):
    def __str__(self):
        return "x"

    def __iter__(self):
        return iter(())


class _Facts(dict):
    """ansible_facts: any fact not given reads as undefined, not KeyError."""
    def __getitem__(self, k):
        return dict.get(self, k, _Lenient(name=k))


class _AnyFilter(dict):
    """Ansible filters are not importable here; unknown ones pass through."""
    def __contains__(self, _):
        return True

    def get(self, k, default=None):
        return dict.get(self, k) or (lambda v, *a, **kw: v)

    __getitem__ = get


def _env() -> jinja2.Environment:
    env = jinja2.Environment(undefined=_Lenient,
                             extensions=["jinja2.ext.do", "jinja2.ext.loopcontrols"])
    flt = _AnyFilter(env.filters)
    flt["bool"] = lambda v: str(v).lower() in ("true", "1", "yes", "on")
    flt["ternary"] = lambda c, a, b=None, n=None: a if c else b
    env.filters = flt
    return env


@functools.lru_cache(maxsize=None)
def _vars(os_family: str) -> dict:
    """default.config.yml with every install_* on, string values resolved the
    way Ansible would (a few lazy passes), facts for one OS family."""
    env = _env()
    cfg = yaml.safe_load((REPO / "default.config.yml").read_text()) or {}
    cfg.update({k: True for k in cfg if k.startswith("install_")})
    facts = _Facts(os_family=os_family, env=_Facts(HOME="/home/nos"), user_id="nos",
                   user_uid=1000, user_gid=1000)
    cfg.update(ansible_os_family=os_family, ansible_facts=facts)
    for _ in range(3):
        for k, v in list(cfg.items()):
            if isinstance(v, str) and "{" in v and not k.startswith("install_"):
                try:
                    cfg[k] = env.from_string(v).render(**cfg)
                except Exception:  # noqa: BLE001 — an unresolvable default stays text
                    pass
    return cfg


def _bind_sources(volumes):
    for v in volumes or []:
        if isinstance(v, dict):
            if v.get("source"):
                yield str(v["source"])
        elif isinstance(v, str) and ":" in v:
            yield v.split(":", 1)[0]


def _exposes_socket(src: str) -> bool:
    return src.rstrip("/").endswith("docker.sock") or (src.rstrip("/") or "/") in SOCKET_DIRS


def socket_mounts(text: str, os_family: str) -> list[tuple[str, str, str]]:
    """(service, image, source) of every bind that reaches the socket."""
    env = _env()
    doc = yaml.safe_load(env.from_string(text).render(**_vars(os_family))) or {}
    services = (doc.get("compose") or doc).get("services") or {}
    return [(name, str(svc.get("image", "")), src)
            for name, svc in services.items() if isinstance(svc, dict)
            for src in _bind_sources(svc.get("volumes"))
            if _exposes_socket(src)]


def offenders(text: str, os_family: str) -> list[str]:
    return [f"{svc} ({image}) mounts {src}"
            for svc, image, src in socket_mounts(text, os_family)
            if not (image.startswith(PROXY_IMAGE) and src.endswith("docker.sock"))
            and (svc, src.rstrip("/") or "/") not in EXCEPTIONS]


def test_there_are_compose_templates_to_check():
    assert len(TEMPLATES) > 80, len(TEMPLATES)


@pytest.mark.parametrize("os_family", ["Darwin", "Debian"])
def test_no_direct_docker_socket(os_family):
    bad, blind = [], []
    for path in TEMPLATES:
        text = path.read_text(encoding="utf-8")
        try:
            bad += [f"{path.relative_to(REPO)}: {o}" for o in offenders(text, os_family)]
        except Exception as e:  # noqa: BLE001
            blind.append(f"{path.relative_to(REPO)}: {e!r}")
    assert not blind, "templates the gate cannot render (blind, not green):\n  " + "\n  ".join(blind)
    assert not bad, (
        f"[{os_family}] Docker socket reached outside a proxy — give the consumer "
        f"its own {PROXY_IMAGE} with minimal sections:\n  " + "\n  ".join(bad))


def test_the_detector_sees_a_direct_mount():
    """Retro-verification against the shapes that were live before this gate."""
    broken = ("services:\n  watchtower:\n    image: w\n    volumes:\n"
              "      - /var/run/docker.sock:/var/run/docker.sock\n"
              "  cadvisor:\n    image: c\n    volumes:\n      - /var/run:/var/run:ro\n"
              "  proxy:\n    image: tecnativa/docker-socket-proxy:v1\n    volumes:\n"
              "      - /var/run/docker.sock:/var/run/docker.sock:ro\n")
    assert len(offenders(broken, "Debian")) == 2


def test_woodpecker_wait_skips_the_proxy_timeout():
    """Woodpecker ignores a ContainerWait error and inspects: a wait cut by the
    stock 10m `timeout server` reads a still-running step as exit 0. The
    agent's proxy must mount the fork whose no-timeout route covers /wait."""
    env = _env()
    text = (REPO / "roles/pazny.woodpecker/templates/compose.yml.j2").read_text()
    svc = yaml.safe_load(env.from_string(text).render(**_vars("Darwin")))["services"]
    mounts = dict(v.split(":")[:2][::-1] for v in svc["woodpecker-socket-proxy"]["volumes"])
    assert Path(mounts["/usr/local/etc/haproxy/haproxy.cfg.template"]).name == \
        "woodpecker-socket-proxy.cfg.template"
    cfg = (REPO / "roles/pazny.woodpecker/files/socket-proxy-haproxy.cfg.template").read_text()
    route = re.search(r"use_backend docker-events if \{ path,url_dec -m reg -i (\S+) \}", cfg)
    assert route, "no-timeout route is gone from the fork"
    for path in ("/v1.45/containers/wp_abc/wait", "/containers/wp_abc/logs", "/events"):
        assert re.match(route.group(1), path, re.I), path
    assert not re.match(route.group(1), "/v1.45/containers/json", re.I)
