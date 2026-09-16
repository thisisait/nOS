"""REM-244 / REM-251 / REM-253 — SOURCE pins, not a live converge.

REM-244: Gitea 1.27.2 is inside the 2026-08-29 advisory wave; 1.27.3 is the
same-minor patched tag. The at-target recipe must move with the pin or a
plain main.yml re-render reverts an applied hop (REM-178).

REM-253: n8n 2.35.7 is below the 2026-09-02 wave floor (< 2.37.7 on all
nineteen GHSAs). Smallest line that clears them is 2.37.7+; the queue named
2.37.10 as the 2.37 head.

REM-251: GHSA-rf44-j88r-hh8c needs Traefik >= v3.7.12 AND
entryPoints.websecure.http.aliasHeadersStrategy delete|reject — the option
defaults to keep, so the bump alone is a no-op. GHSA-v67p-phpq-fc8x then
showed v3.7.12 still forwards spoofed names as trailers; the patched tag is
v3.7.13. Pin that, and set the strategy. websecure is the load-bearing
entrypoint: that is where ForwardAuth identity headers are written.

WHAT THIS CANNOT DO: pull the image or prove the running binary. Those are a
nos + a reader. A green here is the SOURCE shape.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
GITEA_RECIPE = REPO / "upgrades/gitea.yml"
TRAEFIK_STATIC = REPO / "roles/pazny.traefik/templates/traefik.yml.j2"


def _cfg_pin(name: str) -> str:
    m = re.search(rf'^{re.escape(name)}:\s*"([^"]+)"', CONFIG.read_text(encoding="utf-8"), re.M)
    assert m, f"{name} left default.config.yml"
    return m.group(1)


def _tuple(ver: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.sub(r"^[vV]", "", ver).split(".") if p.isdigit())


def _uncomment(text: str) -> str:
    lines = []
    for ln in text.splitlines():
        stripped = ln.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(ln.split("#", 1)[0] if "#" in ln else ln)
    return "\n".join(lines)


def test_gitea_pin_clears_the_aug29_wave() -> None:
    pin = _cfg_pin("gitea_version")
    assert _tuple(pin) >= (1, 27, 3), (
        f"gitea_version is {pin}; REM-244 needs >= 1.27.3"
    )
    recipe = GITEA_RECIPE.read_text(encoding="utf-8")
    at_target = re.search(
        r'id: "gitea-1.27-current".*?to: "(\d+\.\d+\.\d+)"',
        recipe,
        re.S,
    )
    assert at_target, "gitea-1.27-current left upgrades/gitea.yml"
    assert at_target.group(1) == pin, (
        f"recipe to={at_target.group(1)} but pin={pin} — a plain main.yml "
        "re-render would revert the applied hop (REM-178)"
    )


def test_n8n_pin_clears_the_sep2_wave() -> None:
    pin = _cfg_pin("n8n_version")
    assert _tuple(pin) >= (2, 37, 7), (
        f"n8n_version is {pin}; REM-253 needs >= 2.37.7 (nineteen GHSAs, "
        "no CVE ids — vendor advisory endpoint only)"
    )


def test_traefik_pin_and_alias_headers_strategy() -> None:
    pin = _cfg_pin("traefik_image_version")
    assert _tuple(pin) >= (3, 7, 13), (
        f"traefik_image_version is {pin}; REM-251's floor is v3.7.12 but "
        "GHSA-v67p-phpq-fc8x still applies through v3.7.12. Pin v3.7.13."
    )
    body = TRAEFIK_STATIC.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^  websecure:.*?(?=^  ping:|\Z)", body)
    assert m, "websecure entrypoint left traefik.yml.j2"
    http = _uncomment(m.group(0))
    strat = re.search(r"aliasHeadersStrategy:\s*(\S+)", http)
    assert strat, (
        "websecure has no aliasHeadersStrategy. The option defaults to keep, "
        "so a version bump alone does not close GHSA-rf44-j88r-hh8c (REM-251)."
    )
    assert strat.group(1) in {"delete", "reject"}, (
        f"aliasHeadersStrategy is {strat.group(1)!r}; keep is the vulnerable "
        "default. Use delete or reject."
    )
