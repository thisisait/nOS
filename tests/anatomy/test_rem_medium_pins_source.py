"""MEDIUM SOURCE pins and two config holes, not a live converge.

Patch-or-near-patch hops the queue named as auto_fixable, plus two one-line
config gaps. Skipped here on purpose: GitLab 18→19 (REM-159), Firefly 6.2→6.6
(REM-260, four minors), Infisical (no named security fix), FrankenPHP (linux
checksums must move with the pin), Authentik (ghcr tag + tofu estate).

WHAT THIS CANNOT DO: pull images or prove running binaries. nos + a reader.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
GRAFANA_RECIPE = REPO / "upgrades/grafana.yml"
MARIADB_RECIPE = REPO / "upgrades/mariadb.yml"
DNSMASQ = REPO / "tasks/dnsmasq.yml"
MINIFLUX_COMPOSE = REPO / "roles/pazny.miniflux/templates/compose.yml.j2"
MINIFLUX_DEF = REPO / "roles/pazny.miniflux/defaults/main.yml"
NTFY_DEF = REPO / "roles/pazny.ntfy/defaults/main.yml"
MAILPIT_DEF = REPO / "roles/pazny.mailpit/defaults/main.yml"
VW_DEF_OR_CFG = CONFIG  # vaultwarden_version lives in default.config.yml


def _pin_in(path: Path, name: str) -> str:
    m = re.search(rf'^{re.escape(name)}:\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M)
    assert m, f"{name} left {path.relative_to(REPO)}"
    return m.group(1)


def _tuple(ver: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.sub(r"^[vV]", "", ver).split(".") if p.isdigit())


def test_tempo_grafana_mariadb_vaultwarden_pins() -> None:
    assert _tuple(_pin_in(CONFIG, "tempo_version")) >= (2, 10, 8)
    g = _pin_in(CONFIG, "grafana_version")
    assert _tuple(g) >= (12, 4, 10)
    recipe = GRAFANA_RECIPE.read_text(encoding="utf-8")
    at = re.search(r'id: "grafana-12-current".*?to: "(\d+\.\d+\.\d+)"', recipe, re.S)
    assert at and at.group(1) == g, f"grafana recipe to={at and at.group(1)} pin={g}"
    m = _pin_in(CONFIG, "mariadb_version")
    assert _tuple(m) >= (11, 8, 9)
    mrec = MARIADB_RECIPE.read_text(encoding="utf-8")
    mt = re.search(r'id: "mariadb-11-current".*?to: "(\d+\.\d+\.\d+)"', mrec, re.S)
    assert mt and mt.group(1) == m, f"mariadb recipe to={mt and mt.group(1)} pin={m}"
    assert _tuple(_pin_in(CONFIG, "vaultwarden_version")) >= (1, 37, 3)


def test_miniflux_ntfy_mailpit_role_pins() -> None:
    assert _tuple(_pin_in(MINIFLUX_DEF, "miniflux_version")) >= (2, 3, 3)
    assert _tuple(_pin_in(NTFY_DEF, "ntfy_version")) >= (2, 28, 0)
    assert _tuple(_pin_in(MAILPIT_DEF, "mailpit_version")) >= (1, 30, 6)


def _uncomment(text: str) -> str:
    lines = []
    for ln in text.splitlines():
        stripped = ln.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(ln.split("#", 1)[0] if "#" in ln else ln)
    return "\n".join(lines)


def test_miniflux_https_env_is_on() -> None:
    body = _uncomment(MINIFLUX_COMPOSE.read_text(encoding="utf-8"))
    assert re.search(r'HTTPS:\s*"1"', body), (
        "Miniflux BASE_URL is https but HTTPS env is unset — cookies stay "
        "insecure (REM-237). Set HTTPS: \"1\" in the compose template."
    )


def test_dnsmasq_stops_rebind_without_localhost_ok() -> None:
    body = _uncomment(DNSMASQ.read_text(encoding="utf-8"))
    assert "stop-dns-rebind" in body, (
        "dnsmasq forwards upstream answers into RFC1918/loopback (REM-154). "
        "Measured: dig @127.0.0.1 localtest.me → 127.0.0.1."
    )
    assert "rebind-localhost-ok" not in body, (
        "rebind-localhost-ok re-opens the localtest.me relay REM-154 measured. "
        "address=/.{{ tenant }}/ is local, not upstream — it does not need the ok."
    )
