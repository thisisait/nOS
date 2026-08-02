"""An ungated Homebrew call does not skip on Linux — Linuxbrew runs it.

The estate's doctrine is that every brew install is gated on
`nos_pkg_manager == 'homebrew'` (or `ansible_os_family == 'Darwin'`), and the
assumption behind treating that as satisfied was that a brew module simply
no-ops off a Mac. It does not: GitHub's Linux runners ship Linuxbrew on `$PATH`,
so `community.general.homebrew` happily builds from a Linux formula.

Proven 2026-08-02 by the Linux wet-test: `pazny.backup` brew-installed `awscli`
on Ubuntu and died inside Homebrew's own post-install
("unknown install step: run"). Two faults stacked — an upstream Homebrew-on-Linux
bug, and our gate simply not applied. Only the second was ours, and applying it
removes the first from the path entirely. `pazny.acme` and `pazny.opencode`
carried the same defect unproven, because their flags are off in CI.

A brew task is acceptable when EITHER:
  * it (or its enclosing block) is gated in-file on the package manager or on
    Darwin, OR
  * the whole role is Darwin-gated where main.yml includes it, OR
  * it lives in a `pazny.mac.*` role, which is Darwin by definition.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"

BREW_MODULES = (
    "community.general.homebrew",
    "community.general.homebrew_cask",
    "community.general.homebrew_tap",
    "homebrew",
    "homebrew_cask",
    "homebrew_tap",
)

#: Any of these appearing in a `when:` counts as a platform gate.
GATE_TOKENS = ("nos_pkg_manager", "ansible_os_family", "ansible_facts['os_family']",
               'ansible_facts["os_family"]', "is_darwin", "homebrew_prefix is")


def _gated(when) -> bool:
    text = " ".join(when) if isinstance(when, list) else str(when or "")
    return any(tok in text for tok in GATE_TOKENS)


def _walk(tasks, inherited: bool):
    """Yield (task, effectively_gated) over tasks and nested block/rescue."""
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        here = inherited or _gated(t.get("when"))
        for key in ("block", "rescue", "always"):
            if key in t:
                yield from _walk(t[key], here)
        if any(m in t for m in BREW_MODULES):
            yield t, here


def _darwin_gated_roles() -> set[str]:
    """Roles AND tasks/*.yml files whose include site in main.yml is gated.

    Both shapes matter: roles arrive as `name: pazny.x` under include_role, and
    whole task files as `import_tasks: tasks/x.yml`. tailscale + observability
    are the second shape, and a scanner that only understood the first reported
    them as offenders after they had been correctly gated.
    """
    lines = MAIN.read_text().splitlines()
    gated: set[str] = set()
    for i, line in enumerate(lines):
        m = re.search(r"name:\s*(pazny\.[\w.]+)\s*$", line) or re.search(
            r"import_tasks:\s*(tasks/[\w./-]+\.yml)\s*$", line
        )
        if not m:
            continue
        window = "\n".join(lines[i : i + 14])
        # Stop at the next include so we do not borrow a neighbour's gate.
        nxt = re.search(r"\n\s*-\s*(name|import_tasks):\s", window[len(line):])
        if nxt:
            window = window[: len(line) + nxt.start()]
        if _gated(window):
            gated.add(m.group(1))
    return gated


def _role_of(path: Path) -> str | None:
    parts = path.relative_to(REPO).parts
    if parts and parts[0] == "roles":
        return parts[1]
    return None


def test_every_homebrew_call_is_platform_gated():
    darwin_roles = _darwin_gated_roles()
    offenders: list[str] = []

    candidates = sorted(
        list((REPO / "roles").rglob("*.yml")) + list((REPO / "tasks").rglob("*.yml"))
    )
    for path in candidates:
        if "/templates/" in str(path) or "/defaults/" in str(path) or "/meta/" in str(path):
            continue
        try:
            doc = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if not isinstance(doc, list):
            continue

        role = _role_of(path)
        rel = str(path.relative_to(REPO))
        # pazny.mac.* is Darwin by definition; a role — or a whole tasks/ file —
        # gated at its include site in main.yml never reaches Linux.
        if role and (role.startswith("pazny.mac.") or role in darwin_roles):
            continue
        if rel in darwin_roles:
            continue

        for task, gated in _walk(doc, inherited=False):
            if not gated:
                offenders.append(
                    f"{path.relative_to(REPO)}: {task.get('name', '<unnamed>')!r}"
                )

    assert not offenders, (
        "Homebrew tasks that RUN on Linux (Linuxbrew is on $PATH — a brew module "
        "does not skip off a Mac). Gate on `nos_pkg_manager == 'homebrew'`, or "
        "Darwin-gate the role where main.yml includes it:\n  "
        + "\n  ".join(offenders)
    )


def test_the_include_site_scanner_finds_the_known_darwin_roles():
    """Guard the guard: if this parser silently found nothing, the gate above
    would pass by excluding everything instead of by everything being gated."""
    gated = _darwin_gated_roles()
    for role in ("pazny.openclaw", "pazny.hermes", "pazny.acme",
                 "tasks/tailscale.yml", "tasks/observability.yml"):
        assert role in gated, (
            f"{role} is Darwin-gated in main.yml but the include-site scanner "
            f"did not see it — the exclusion list is being built wrong, which "
            f"would make the main gate too STRICT, not too loose. Found: {sorted(gated)}"
        )
    assert "pazny.backup" not in gated, (
        "pazny.backup is NOT Darwin-gated in main.yml (it is armed on "
        "install_backup alone) — if the scanner thinks it is, the main gate "
        "would have excused the very task that broke the Linux wet-test"
    )
