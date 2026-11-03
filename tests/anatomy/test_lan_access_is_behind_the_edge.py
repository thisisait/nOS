"""With services_lan_access off, no role publishes a port beyond loopback.

Row lan-access-is-behind-the-edge: the edge (Traefik) is the only door to the
LAN; every other published port binds 127.0.0.1. The gate RENDERS every
roles/*/templates/compose.yml.j2 on Darwin and Linux facts, with the toggle
false AND absent (a bare `{% if services_lan_access %}` is an undefined-var
crash in Ansible; `| default(false)` keeps it loopback), and reads `ports:`.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from test_docker_sock_only_behind_proxy import _Lenient, _env, _vars

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = sorted(REPO.glob("roles/*/templates/compose.yml.j2"))
#: (role, container port) -> why it may face the LAN.
EDGE = {
    ("pazny.traefik", "80"): "the edge",
    ("pazny.traefik", "443"): "the edge",
    ("pazny.traefik", "8443"): "the edge (origin pull)",
    **{("pazny.smtp_stalwart", p): "raw SMTP/IMAP TCP cannot ride Traefik; "
       "own opt-in stalwart_lan_only (see the template header)"
       for p in ("25", "465", "587", "993")},
}
#: Roles another work item owns; out of scope here.
OWNED_ELSEWHERE = {
    "pazny.jellyfin",   # jellyfin_lan_access — the jellyfin LAN item
    "pazny.paperclip",  # its compose belongs to the paperclip-company work
}


class _AbsentToggle(_Lenient):
    """services_lan_access undefined: testing it bare is Ansible's crash."""
    def __bool__(self):
        if self._undefined_name == "services_lan_access":
            raise RuntimeError("services_lan_access tested without | default(false)")
        return False


def lan_ports(text: str, os_family: str, absent: bool) -> list[str]:
    env = _env()
    tvars = dict(_vars(os_family))
    if absent:
        env.undefined = _AbsentToggle
        tvars.pop("services_lan_access", None)
    else:
        tvars["services_lan_access"] = False
    doc = yaml.safe_load(env.from_string(text).render(**tvars)) or {}
    return [(name, str(p))
            for name, svc in (doc.get("services") or {}).items() if isinstance(svc, dict)
            for p in svc.get("ports") or []
            if not str(p).startswith("127.0.0.1:")]


def _container_port(port: str) -> str:
    return port.rsplit(":", 1)[-1].split("/")[0]


@pytest.mark.parametrize("absent", [False, True], ids=["false", "absent"])
@pytest.mark.parametrize("os_family", ["Darwin", "Debian"])
def test_every_published_port_is_loopback(os_family, absent):
    bad = []
    for path in TEMPLATES:
        role = path.parts[-3]
        if role in OWNED_ELSEWHERE:
            continue
        try:
            ports = lan_ports(path.read_text(encoding="utf-8"), os_family, absent)
        except Exception as e:  # noqa: BLE001 — blind is red, not green
            bad.append(f"{role}: does not render: {e}")
            continue
        bad += [f"{role}/{svc}: {p}" for svc, p in ports
                if (role, _container_port(p)) not in EDGE]
    assert not bad, (
        f"[{os_family}, services_lan_access {'absent' if absent else 'false'}] a port "
        "faces the LAN — bind 127.0.0.1 unless `services_lan_access | default(false)`:\n  "
        + "\n  ".join(bad))


def test_the_detector_sees_a_lan_port():
    broken = ('services:\n  app:\n    ports:\n{% if services_lan_access %}'
              '\n      - "8080:80"\n{% else %}\n      - "127.0.0.1:8080:80"\n{% endif %}\n')
    assert lan_ports(broken, "Debian", absent=False) == []
    with pytest.raises(RuntimeError):
        lan_ports(broken, "Debian", absent=True)
    assert lan_ports('services:\n  app:\n    ports: ["8080:80", "9000"]\n',
                     "Darwin", absent=False) == [("app", "8080:80"), ("app", "9000")]
