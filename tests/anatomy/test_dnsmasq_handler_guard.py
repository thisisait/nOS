"""Anatomy CI gate — dnsmasq restart handler must guard the launchctl plist.

The `Restart dnsmasq` handler in main.yml drives a system LaunchDaemon via
`sudo launchctl unload/load /Library/LaunchDaemons/homebrew.mxcl.dnsmasq.plist`.
The path is installed by the Homebrew dnsmasq formula. If a future formula
(macOS 27+) relocates the plist, an unguarded unload/load silently no-ops
behind `2>/dev/null` and DNS quietly breaks.

The fix mirrors the proven defensive pattern already used by the `Restart
nginx` and `Restart alloy` handlers: a `[ -f "$plist" ]` existence check
before touching launchctl, so a missing plist is surfaced (no restart
attempted) rather than masked.

This gate pins:
  1. The dnsmasq handler binds the plist to a `plist=` shell var (no longer a
     hardcoded inline path on the launchctl lines).
  2. The handler guards launchctl with a `[ ! -f "$plist" ]` / `[ -f "$plist" ]`
     existence check (the nginx/alloy pattern).
  3. The handler is Darwin-gated (`when: ansible_os_family == 'Darwin'`).
  4. `dnsmasq_version` is pinned in default.config.yml with a stock-Jinja-safe
     literal (no non-stock filters that would trip the {{ vars }} eager-resolve
     trap in the core-up loader).

Auto-fails if the guard is removed or the version pin disappears.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_YML = REPO_ROOT / "main.yml"
DEFAULT_CONFIG = REPO_ROOT / "default.config.yml"


def _dnsmasq_handler_block() -> str:
    """Return the raw text of the `Restart dnsmasq` handler block.

    Slices from the handler's `- name: Restart dnsmasq` line up to the next
    top-level handler `- name:` marker.
    """
    src = MAIN_YML.read_text()
    start = src.find("- name: Restart dnsmasq")
    assert start != -1, "`- name: Restart dnsmasq` handler not found in main.yml"
    # Find the next handler entry at the same indentation (4 spaces + '- name:').
    rest = src[start + len("- name: Restart dnsmasq"):]
    nxt = re.search(r"\n    - name: ", rest)
    end = start + len("- name: Restart dnsmasq") + (nxt.start() if nxt else len(rest))
    return src[start:end]


def test_dnsmasq_handler_uses_plist_var():
    """The handler must bind the plist to a shell var, not hardcode it inline
    on the launchctl lines."""
    block = _dnsmasq_handler_block()
    assert 'plist="/Library/LaunchDaemons/homebrew.mxcl.dnsmasq.plist"' in block, (
        "dnsmasq handler must assign the plist path to a `plist=` shell var "
        "(matching the nginx/alloy defensive pattern)"
    )
    # launchctl must reference "$plist", not the raw inline path.
    assert re.search(r"launchctl\s+unload\s+\"\$plist\"", block), (
        "dnsmasq handler `launchctl unload` must use \"$plist\", not an inline path"
    )
    assert re.search(r"launchctl\s+load\s+\"\$plist\"", block), (
        "dnsmasq handler `launchctl load` must use \"$plist\", not an inline path"
    )


def test_dnsmasq_handler_has_existence_guard():
    """The handler must guard launchctl behind a plist-existence check —
    the same hardening the nginx/alloy handlers carry."""
    block = _dnsmasq_handler_block()
    has_guard = ('[ ! -f "$plist" ]' in block) or ('[ -f "$plist" ]' in block)
    assert has_guard, (
        "dnsmasq handler must guard the launchctl unload/load behind a "
        "`[ -f \"$plist\" ]` existence check (the nginx/alloy pattern). Without "
        "it, a relocated Homebrew formula plist silently no-ops and DNS breaks."
    )


def test_dnsmasq_handler_is_darwin_gated():
    """The launchctl/Homebrew plist path is macOS-only — the handler must be
    Darwin-gated so a Linux run never reaches it."""
    block = _dnsmasq_handler_block()
    assert "ansible_os_family == 'Darwin'" in block, (
        "dnsmasq handler must carry `when: ansible_os_family == 'Darwin'` — "
        "the Homebrew LaunchDaemon path is macOS-only"
    )


def test_dnsmasq_version_pinned():
    """`dnsmasq_version` must be a pinned literal in default.config.yml."""
    data = yaml.safe_load(DEFAULT_CONFIG.read_text()) or {}
    assert "dnsmasq_version" in data, (
        "dnsmasq_version pin missing from default.config.yml"
    )
    val = data["dnsmasq_version"]
    assert isinstance(val, str) and val.strip(), (
        f"dnsmasq_version must be a non-empty string literal, got {val!r}"
    )
    # A plain version literal — no Jinja templating that could trip the
    # {{ vars }} eager-resolve trap in the core-up loader.
    assert "{{" not in val and "{%" not in val, (
        f"dnsmasq_version must be a stock literal (no Jinja), got {val!r}"
    )
