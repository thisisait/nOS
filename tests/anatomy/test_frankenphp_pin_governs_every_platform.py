"""The FrankenPHP pin decides the binary on macOS too, not only on Linux.

thisisait/nOS#48: Linux fetched ``v{{ frankenphp_version }}`` from the GitHub
release with a sha256, so pin and binary always agreed. macOS ran
``homebrew: dunglas/frankenphp/frankenphp`` — a tap formula has no version
selector, so it installed the tap's latest. Every upstream release then broke
every FRESH macOS install at "Refuse on frankenphp version mismatch", while
existing hosts kept their older Cellar keg and stayed green — invisible to the
maintainer, deterministic for a newcomer.

The rule this pins: the one task that lands the FrankenPHP binary is the
pinned, checksummed release fetch, and it resolves to a real asset with a
recorded checksum on every platform nOS supports. No Homebrew task may
install a frankenphp formula (it would land an unpinned binary beside it).

The URL and checksum are RENDERED per platform here, not grepped, so a
platform whose asset name or checksum key does not exist is red.
"""

from __future__ import annotations

import pathlib
import sys

import jinja2
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import nos_identity as ni  # noqa: E402

WING_TASKS = REPO / "roles/pazny.wing/tasks/main.yml"

# (ansible_os_family, ansible_architecture, the release asset it must fetch)
PLATFORMS = [
    ("Darwin", "arm64", "frankenphp-mac-arm64"),
    ("Darwin", "x86_64", "frankenphp-mac-x86_64"),
    ("Debian", "aarch64", "frankenphp-linux-aarch64"),
    ("Debian", "x86_64", "frankenphp-linux-x86_64"),
]


def _tasks():
    out = []

    def walk(items):
        for t in items or []:
            if isinstance(t, dict):
                out.append(t)
                for key in ("block", "rescue", "always"):
                    walk(t.get(key))

    walk(yaml.safe_load(WING_TASKS.read_text(encoding="utf-8")))
    return out


def _frankenphp_fetches():
    return [
        t for t in _tasks()
        if "frankenphp" in str((t.get("ansible.builtin.get_url") or t.get("get_url") or {}).get("url", ""))
    ]


def _render(expr: str, **ctx) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(expr).render(**ctx)


def test_no_homebrew_task_installs_a_frankenphp_formula():
    offenders = []
    for t in _tasks():
        mod = t.get("community.general.homebrew") or t.get("homebrew")
        if not isinstance(mod, dict):
            continue
        names = mod.get("name")
        names = names if isinstance(names, list) else [names]
        if any(str(n).split("/")[-1] == "frankenphp" for n in names):
            offenders.append(t.get("name"))
    assert not offenders, (
        f"{offenders}: a Homebrew frankenphp formula has no version selector — "
        "it lands the tap's latest, not frankenphp_version (#48)"
    )


def test_one_fetch_serves_every_platform():
    fetches = _frankenphp_fetches()
    assert len(fetches) == 1, f"expected ONE frankenphp release fetch, found {len(fetches)}"
    when = fetches[0].get("when")
    assert "Darwin" not in str(when or ""), (
        f"the frankenphp fetch is gated on the OS ({when!r}); macOS must take "
        "the same pinned path as Linux"
    )


@pytest.mark.parametrize("family,arch,asset", PLATFORMS)
def test_fetch_renders_the_pinned_asset_with_a_checksum(family, arch, asset):
    cfg = yaml.safe_load(ni.default_config_text())
    mod = _frankenphp_fetches()[0].get("ansible.builtin.get_url") or _frankenphp_fetches()[0]["get_url"]
    ctx = {
        "ansible_os_family": family,
        "ansible_architecture": arch,
        "frankenphp_version": cfg["frankenphp_version"],
        "frankenphp_checksums": cfg.get("frankenphp_checksums", {}),
    }
    task = _frankenphp_fetches()[0]
    for key, expr in (task.get("vars") or {}).items():  # task vars, in order
        ctx[key] = _render(str(expr), **ctx).strip()
    url = _render(mod["url"], **ctx)
    assert url == (
        f"https://github.com/php/frankenphp/releases/download/"
        f"v{cfg['frankenphp_version']}/{asset}"
    ), url
    checksum = _render(mod["checksum"], **ctx)
    assert checksum.startswith("sha256:") and len(checksum) == len("sha256:") + 64, (
        f"{family}/{arch}: no recorded sha256 for {asset} (got {checksum!r})"
    )
