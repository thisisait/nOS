"""Anatomy CI gate — blank-reset must discover all playbook-managed LaunchAgents.

When blank=true runs, tasks/blank-reset.yml:136-155 uses ansible.builtin.find
to discover plist files under ~/Library/LaunchAgents/ matching a list of
patterns. If a new playbook-managed agent is added (e.g., bone, pulse, wing) but
NOT added to the patterns list, the agent's plist survives the blank reset and
persists into the next playbook run → stale/broken agent state, cross-version
pollution.

This gate:
  1. Enumerates all roles that create LaunchAgent plists (bone, pulse, wing,
     backup, backup-exporter, hermes, acme, openclaw)
  2. Extracts the actual Label from each role's .plist.j2 template
  3. Extracts the default label value from each role's defaults/main.yml
  4. Asserts each label's .plist filename is in blank-reset.yml patterns

The gate auto-fails if a new agent role is added but the blank-reset patterns
are not updated.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BLANK_RESET_PATH = REPO_ROOT / "tasks" / "blank-reset.yml"
ROLES_DIR = REPO_ROOT / "roles"

# Patterns the blank intentionally cleans up but that no longer have a template
# in-repo: an old label a service used BEFORE it migrated to its current one.
# Keeping the pattern lets a blank evict the stale plist on a pre-migration host.
# Add here (with the migration noted) rather than deleting from blank-reset.yml.
LEGACY_CLEANUP_PATTERNS = {
    # hermes ran under com.hermes.agent before migrating to eu.thisisait.nos.hermes
    "com.hermes.agent.plist",
}

# Provisioned at RUNTIME by a CLI (not a role `.plist.j2`), but legitimately
# nOS-managed so a blank/uninstall MUST remove them. `ai.openclaw.gateway.plist`
# is created by `openclaw gateway install`; nOS provisions OpenClaw via
# `npm install -g openclaw` (roles/pazny.openclaw). Left running, it re-creates
# ~/.openclaw right after a wipe (found during the 2026-07-19 uninstall).
RUNTIME_PROVISIONED_PATTERNS = {
    "ai.openclaw.gateway.plist",
}

# Repo-managed plists that the OWNING role already removes itself on every run,
# so blank-reset need not (and does not) list them. Excluded from the
# completeness gate to avoid demanding a redundant pattern.
SELF_CLEANED_PLISTS = {
    # backup role boots out + removes the legacy colliding label every run
    # (roles/pazny.backup/tasks/main.yml "[backup] Remove legacy colliding plist")
    "eu.thisisait.nos.backup.plist",
    # openclaw role renames brew's plist to .disabled every run, then blank-reset
    # evicts the .disabled form (roles/pazny.openclaw/tasks/main.yml line 56).
    "homebrew.mxcl.ollama.plist",
}


# Mapping of role → (plist_template_name, label_var_name, label_default)
# This defines the contract between each role and blank-reset.yml
PLAYBOOK_AGENTS = {
    "pazny.bone": {
        "template": "bone.plist.j2",
        "label_var": "bone_launchd_label",
        "label_default": "eu.thisisait.nos.bone",
    },
    "pazny.pulse": {
        "template": "pulse.plist.j2",
        "label_var": "pulse_launchd_label",
        "label_default": "eu.thisisait.nos.pulse",
    },
    "pazny.wing": {
        "template": "wing.plist.j2",
        "label_var": "wing_launchd_label",
        "label_default": "eu.thisisait.nos.wing",
    },
    "pazny.hermes": {
        "template": "hermes.plist.j2",
        "label_var": "hermes_launchd_label",
        "label_default": "eu.thisisait.nos.hermes",
    },
    "pazny.backup": {
        # Backup creates TWO agents
        "templates": [
            ("backup-launchd.plist.j2", "backup_launchd_label", "eu.thisisait.nos.backup.rustfs"),
            ("backup-exporter.plist.j2", "backup_exporter_launchd_label", "eu.thisisait.nos.backup.exporter"),
        ],
    },
    "pazny.acme": {
        "template": "acme-renew.plist.j2",
        "label_var": "acme_renewal_label",
        "label_default": "eu.thisisait.nos.acme-renew",
    },
    "pazny.openclaw": {
        "template": "com.ollama.agent.plist.j2",
        "label_var": None,  # openclaw's plist has a hardcoded label, not a template var
        "label_default": "com.ollama.agent",
    },
}


def _extract_label_from_plist_template(plist_path: Path) -> str | None:
    """Extract the label string from a LaunchAgent plist.j2 template.

    Looks for `<string>{{ var_name }}</string>` or `<string>literal</string>`
    after `<key>Label</key>`.
    """
    content = plist_path.read_text()
    # Match the Label block: <key>Label</key> followed by <string>...</string>
    match = re.search(
        r"<key>Label</key>\s*<string>(.*?)</string>",
        content,
        re.DOTALL,
    )
    if not match:
        return None
    raw = match.group(1).strip()
    # If it's a Jinja template variable, return None — we'll look it up in defaults.
    if raw.startswith("{{"):
        return None
    # Otherwise it's a literal string (e.g. com.ollama.agent)
    return raw


def _extract_label_default_from_defaults(role_path: Path, label_var: str) -> str | None:
    """Extract the default value of a label variable from defaults/main.yml."""
    defaults_file = role_path / "defaults" / "main.yml"
    if not defaults_file.is_file():
        return None

    content = defaults_file.read_text()
    data = yaml.safe_load(content) or {}

    # Handle nested defaults like backup_launchd_label
    if label_var in data:
        return str(data[label_var])
    return None


def _blank_reset_plist_patterns() -> list[str]:
    """Return the find-task ``patterns`` list from blank-reset.yml.

    Parses the file as YAML (comments + ordering are irrelevant) and pulls the
    patterns off the ``[BLANK] Find playbook-managed LaunchAgents`` task — only
    the entries that name a ``.plist``. A YAML parse is robust to interleaved
    comments, whereas a line regex silently truncates at the first comment line.
    """
    tasks = yaml.safe_load(BLANK_RESET_PATH.read_text()) or []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        find = task.get("ansible.builtin.find") or task.get("find")
        if isinstance(find, dict) and "patterns" in find:
            pats = find["patterns"]
            if isinstance(pats, list) and any(".plist" in str(p) for p in pats):
                return [str(p) for p in pats if ".plist" in str(p)]
    raise AssertionError(
        "no ansible.builtin.find task with a .plist patterns list in blank-reset.yml"
    )


def test_blank_reset_plist_patterns_exists():
    """Static gate: the blank-reset patterns block must exist."""
    src = BLANK_RESET_PATH.read_text()
    assert "ansible.builtin.find:" in src, "find task missing from blank-reset.yml"
    assert "patterns:" in src, "patterns list missing from blank-reset.yml"


def test_each_playbook_agent_has_plist_template():
    """Sanity: every registered agent has a plist template file."""
    for role_name, info in PLAYBOOK_AGENTS.items():
        role_path = ROLES_DIR / role_name
        assert role_path.is_dir(), f"role {role_name} not found"

        # Handle both single template and multi-template agents
        templates = info.get("templates")
        if templates:
            for template_name, _, _ in templates:
                template_path = role_path / "templates" / template_name
                assert template_path.is_file(), (
                    f"role {role_name}: template {template_name} missing"
                )
        else:
            template_path = role_path / "templates" / info["template"]
            assert template_path.is_file(), (
                f"role {role_name}: template {info['template']} missing"
            )


def test_blank_reset_covers_all_agents():
    """Core gate: every playbook-managed agent's plist filename must be in
    blank-reset.yml patterns.

    This is the main anti-regression check: if a new agent is added without
    updating blank-reset.yml, this test fails.
    """
    patterns = _blank_reset_plist_patterns()

    missing_agents = []

    for role_name, info in PLAYBOOK_AGENTS.items():
        role_path = ROLES_DIR / role_name
        if not role_path.is_dir():
            continue

        # Handle both single template and multi-template agents
        templates_info = []
        if "templates" in info:
            templates_info = info["templates"]
        else:
            templates_info = [
                (info["template"], info.get("label_var"), info.get("label_default"))
            ]

        for template_name, label_var, label_default in templates_info:
            template_path = role_path / "templates" / template_name
            if not template_path.is_file():
                continue

            # Extract label from template
            literal_label = _extract_label_from_plist_template(template_path)
            if literal_label:
                # Plist has a hardcoded label
                actual_label = literal_label
            else:
                # Label is templated — get the default value
                if label_var:
                    actual_label = _extract_label_default_from_defaults(
                        role_path, label_var
                    )
                else:
                    actual_label = label_default

            if not actual_label:
                continue

            plist_filename = f"{actual_label}.plist"

            # Check if this pattern is in blank-reset.yml
            if plist_filename not in patterns:
                missing_agents.append({
                    "role": role_name,
                    "template": template_name,
                    "label": actual_label,
                    "plist_filename": plist_filename,
                })

    if missing_agents:
        msg = (
            "blank-reset.yml patterns missing the following playbook-managed agents:\n"
        )
        for agent in missing_agents:
            msg += (
                f"\n  - Role: {agent['role']}\n"
                f"    Template: {agent['template']}\n"
                f"    Label: {agent['label']}\n"
                f"    Plist filename to add: {agent['plist_filename']}"
            )
        msg += (
            "\n\nAdd these patterns to tasks/blank-reset.yml:139-146 "
            "(the find patterns block)."
        )
        pytest.fail(msg)


def _global_label_var_map() -> dict[str, str]:
    """Merge every scalar default from role defaults + default.config.yml.

    A launchd label can be defined in a role's defaults/main.yml (most agents)
    OR centrally in default.config.yml (e.g. restic_launchd_label), and a plist
    template can live OUTSIDE its owning role (templates/…offsite.plist.j2). A
    single flat var→value map lets the scan resolve a templated label/dest no
    matter where the var or the template lives.
    """
    var_map: dict[str, str] = {}
    sources = list((ROLES_DIR).glob("*/defaults/main.yml"))
    cfg = REPO_ROOT / "default.config.yml"
    if cfg.is_file():
        sources.append(cfg)
    for src in sources:
        if ".ci-venv" in src.parts:
            continue
        try:
            data = yaml.safe_load(src.read_text()) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            # Only scalars that look fully resolved (no nested Jinja indirection).
            if isinstance(value, str) and "{{" not in value:
                var_map.setdefault(key, value)
    return var_map


def _repo_managed_plist_filenames() -> set[str]:
    """Scan the repo for every LaunchAgent plist filename the playbook manages.

    Two sources, both authoritative:
      1. ``*.plist.j2`` templates — the Label key, kept literal or resolved from
         the global var map when it is a single ``{{ var }}``. A legacy template
         no longer actively deployed (com.openclaw.agent, com.hermes.agent) still
         counts: its blank-reset pattern is a legitimate pre-migration cleanup.
      2. ``LaunchAgents/<name>.plist`` destinations written by a
         ``template``/``copy`` task or a shell rm — literal, or a single
         ``{{ var }}`` resolved against the same map (e.g. the off-site backup
         plist whose dest is ``{{ restic_launchd_label }}.plist``).
    """
    names: set[str] = set()
    var_map = _global_label_var_map()
    search_roots = [
        REPO_ROOT / "roles",
        REPO_ROOT / "tasks",
        REPO_ROOT / "files",
        REPO_ROOT / "templates",
    ]

    # Source 1: plist.j2 template Labels (skip the vendored .ci-venv tree)
    for root in search_roots:
        if not root.is_dir():
            continue
        for tpl in root.rglob("*.plist.j2"):
            if ".ci-venv" in tpl.parts:
                continue
            label = _extract_label_from_plist_template(tpl)
            if label:
                names.add(f"{label}.plist")
                continue
            # Templated label → resolve the single {{ var }} against the map.
            m = re.search(
                r"<key>Label</key>\s*<string>\{\{\s*([a-z0-9_]+)",
                tpl.read_text(),
            )
            if m and m.group(1) in var_map:
                names.add(f"{var_map[m.group(1)]}.plist")

    # Source 2: LaunchAgents/<name>.plist destinations in task/shell text.
    literal_re = re.compile(r"LaunchAgents/([A-Za-z0-9._{}\s|-]+?\.plist)")
    var_dest_re = re.compile(r"^\{\{\s*([a-z0-9_]+)\s*\}\}\.plist$")
    for root in (REPO_ROOT / "roles", REPO_ROOT / "tasks", REPO_ROOT / "files"):
        if not root.is_dir():
            continue
        for yml in list(root.rglob("*.yml")) + list(root.rglob("*.yaml")):
            if ".ci-venv" in yml.parts:
                continue
            for hit in literal_re.findall(yml.read_text()):
                hit = hit.strip()
                if "{{" not in hit:
                    names.add(hit)
                    continue
                vm = var_dest_re.match(hit)
                if vm and vm.group(1) in var_map:
                    names.add(f"{var_map[vm.group(1)]}.plist")
    return names


def test_blank_reset_patterns_all_exist_in_some_role():
    """Inverse check: every pattern in blank-reset.yml corresponds to an
    actual playbook-managed LaunchAgent plist (no dead patterns).

    Catches obsolete patterns left behind after an agent is retired. Disabled
    and homebrew.* transitional variants are exempt by construction.
    """
    patterns = _blank_reset_plist_patterns()
    expected_filenames = _repo_managed_plist_filenames()

    problematic = []
    for pattern in patterns:
        # Disabled variants + homebrew.* are transitional cleanup entries.
        if ".disabled" in pattern or pattern.startswith("homebrew."):
            continue
        # Documented legacy labels (pre-migration cleanup) are intentional.
        if pattern in LEGACY_CLEANUP_PATTERNS:
            continue
        # Runtime-provisioned (CLI-created) daemons nOS still owns + must remove.
        if pattern in RUNTIME_PROVISIONED_PATTERNS:
            continue
        if pattern not in expected_filenames:
            problematic.append(pattern)

    if problematic:
        pytest.fail(
            "blank-reset.yml has obsolete patterns (no managed plist in the repo): "
            f"{problematic}. Remove from the find patterns block in tasks/blank-reset.yml."
        )


def test_blank_reset_covers_every_repo_managed_plist():
    """Completeness gate (stronger than the role-map check): EVERY plist the
    playbook writes into ~/Library/LaunchAgents must be a blank-reset pattern.

    The role-map gate (test_blank_reset_covers_all_agents) only knows about the
    curated PLAYBOOK_AGENTS roles; this one scans the whole repo, so it also
    catches plain-task-deployed plists (heartbeat, backup.offsite) that no role
    defaults model. Add a new plist destination anywhere → this fails until the
    blank-reset find patterns list it. Self-cleaned legacy labels are exempt.
    """
    patterns = set(_blank_reset_plist_patterns())
    managed = _repo_managed_plist_filenames()

    uncovered = sorted(
        name
        for name in managed
        if name not in patterns
        and name not in SELF_CLEANED_PLISTS
        and name not in LEGACY_CLEANUP_PATTERNS
    )

    if uncovered:
        pytest.fail(
            "blank-reset.yml find patterns miss these playbook-deployed plists "
            f"(they would survive a blank): {uncovered}. Add each to the find "
            "patterns block in tasks/blank-reset.yml — or, if a role already "
            "removes it on every run, add it to SELF_CLEANED_PLISTS with the "
            "removing task noted."
        )


