"""P1 gate — no rendered artifact may contain the master.

The property this whole change exists for (docs/secrets-p1-hkdf.md): on a
scheme-v2 host the master is 32 random bytes that appear in exactly one file
(~/.nos/secrets.yml, 0600) and in NO render — not a compose override, not a
Traefik middleware, not a plugin manifest, not a plist. Three layers:

1. VALUE layer (fixture-driven, retro-verified in-file): every v2 map value is
   checked for master containment in both encodings — and the SAME checker run
   against a v1 map MUST flag every value, because v1 embeds the prefix by
   construction. A checker that passes v1 is decoration.
2. NAME layer: `nos_secret_master` may be referenced only where the design
   puts it (the module invocation, the persistence template, the P1b bridge
   call, the derivation core + its consumers). A reference appearing in a
   role/plugin template means someone is about to render the master.
3. CONCATENATION layer: no template or task may build a NEW credential by
   concatenating `global_password_prefix` — the sites that legitimately still
   touch the prefix are enumerated with their reasons.
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "files/anatomy/module_utils"))

import nos_secret_derive as d  # noqa: E402

REGISTRY = REPO / "files/anatomy/secrets/registry.yml"
FIXTURE_MASTER = bytes(range(32, 64))


def _contains_master(value: str, master: bytes, prefix: str) -> bool:
    hexm = master.hex()
    b64m = base64.urlsafe_b64encode(master).decode().rstrip("=")
    return hexm in value or b64m in value or (prefix and prefix in value)


def test_v2_values_carry_no_trace_of_the_master():
    reg = d.load_registry(str(REGISTRY))
    v2 = d.build_map("v2", reg, prefix="fixture-prefix-xyz",
                     master_hex=FIXTURE_MASTER.hex())
    dirty = [k for k, v in v2.items()
             if _contains_master(v, FIXTURE_MASTER, "fixture-prefix-xyz")]
    assert not dirty, f"v2 values contain master material: {dirty}"


def test_the_checker_goes_red_against_a_v1_map():
    """Retro-verification, permanent: v1 values embed the prefix by
    construction, so the same containment checker must flag ALL of them."""
    reg = d.load_registry(str(REGISTRY))
    v1 = d.build_map("v1", reg, prefix="fixture-prefix-xyz")
    flagged = [k for k, v in v1.items()
               if _contains_master(v, FIXTURE_MASTER, "fixture-prefix-xyz")]
    assert len(flagged) == len(reg), (
        "the containment checker no longer detects the v1 defect — it cannot "
        "be trusted to detect a v2 leak either"
    )


#: The only places the master's NAME may appear, each with its role.
_MASTER_NAME_ALLOWED = {
    "main.yml",                                   # the set_fact + module call
    "templates/secrets.yml.j2",                   # the 0600 persistence
    "tasks/stacks/bluesky_pds_bridge.yml",        # P1b user_leaf module call
    "files/anatomy/module_utils/nos_secret_derive.py",
    "files/anatomy/library/nos_secret_map.py",
    "files/anatomy/secrets/registry.yml",         # doc comment
    "tools/nos-secret.py",                        # the operator reader
    "docs/secrets-p1-hkdf.md",
    "docs/archive/secret-blast-radius.md",
}


def test_master_name_is_referenced_only_where_designed():
    offenders = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in {
            ".yml", ".yaml", ".j2", ".py", ".sh", ".cfg", ".conf", ".js", ".php", ".md"
        }:
            continue
        rel = str(path.relative_to(REPO))
        # `.claude/worktrees/` is a CHECKOUT OF THIS REPO, created by isolated
        # agents. Scanning it re-reports the main tree's own files under a second
        # path and makes the verdict depend on which worktrees happen to be left
        # lying about — this gate went red on 2026-08-28 for exactly that, with
        # nine hits that were all one agent's sibling checkout.
        if rel.startswith((".git/", ".ci-venv/", "tests/", "docs/devlog/",
                           ".claude/worktrees/")):
            continue
        if rel in _MASTER_NAME_ALLOWED:
            continue
        try:
            if "nos_secret_master" in path.read_text(encoding="utf-8"):
                offenders.append(rel)
        except (UnicodeDecodeError, OSError):
            continue
    assert not offenders, (
        "`nos_secret_master` is referenced outside the designed surface — a "
        "render of the master is one template away:\n  " + "\n  ".join(offenders)
    )


#: Files that may still CONCATENATE the prefix into a value, and why.
_CONCAT_ALLOWED = {
    # Reconstructs the RETIRED archive key so pre-P2 archives still open —
    # it reads the past and must keep concatenating forever (P2 sequencing
    # note) — plus the lazy-mint guards keyed on the `_pw_` shape and the
    # bone fallback in the play vars.
    "main.yml",
    # Old-password GUESSES for prefix-rotation reconciles: each computes the
    # value a v1 host would have used BEFORE this run (previous_password_
    # prefix), which the map cannot give it. Wrong-but-harmless on v2.
    "roles/pazny.jellyfin/tasks/post.yml",
    "roles/pazny.uptime_kuma/tasks/monitors.yml",
    "roles/pazny.n8n/tasks/post.yml",
    "roles/pazny.portainer/tasks/post.yml",
    "roles/pazny.metabase/tasks/post.yml",
    # HUMAN_TYPED exceptions (see test_secret_blast_radius.HUMAN_TYPED).
    "default.credentials.yml",                     # ntfy_admin_password
    "roles/pazny.nodered/defaults/main.yml",       # break-glass local admin
    # BLOCKED crown jewel (restic) + the lazy-minted `_pw_`-shaped defaults
    # whose guards key on that exact shape + the bone_secret fallback.
    "default.config.yml",
    # Pulse-catalog literals: the discover script substitutes the WHOLE
    # `{{ global_password_prefix }}_pw_agent_x` literal into a
    # `secret:agent_x_client_secret` reference resolved from the store at
    # exec time — and the store row now carries the map value, so both
    # schemes agree. Verified by the blank-path adversarial lens.
    "files/anatomy/agents",
}

#: Any line that couples the prefix to the `_pw_` rule, in ANY spelling —
#: `{{ prefix }}_pw_x`, `prefix + '_pw_x'`, `prefix ~ '_pw_x'`, AND the form
#: the first regex missed entirely: `{{ previous | default(prefix) }}_pw_x`.
#: The adversarial review showed the narrow regex matched none of the six
#: real surviving sites — a vacuous gate. Coarse on purpose: a false positive
#: costs an allowlist line with a written reason; a false negative is REM-144.
_CONCAT = re.compile(r"global_password_prefix.*_pw_|_pw_.*global_password_prefix")


def test_no_new_prefix_concatenation_outside_the_allowlist():
    offenders = []
    roots = [REPO / "roles", REPO / "tasks", REPO / "templates",
             REPO / "files/anatomy/plugins", REPO / "files/anatomy/library",
             REPO / "files/anatomy/module_utils", REPO / "files/anatomy/agents",
             REPO / "files/observability", REPO / "apps", REPO / "state"]
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".yml", ".yaml", ".j2"}:
                continue
            rel = str(path.relative_to(REPO))
            if rel in _CONCAT_ALLOWED or any(
                rel.startswith(a + "/") for a in _CONCAT_ALLOWED
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if _CONCAT.search(line):
                    offenders.append(f"{rel}:{n}")
    # (The vars files + main.yml are outside `roots` on purpose: their
    # remaining concatenations are counted BY NAME with justifications in
    # test_secret_blast_radius.py — two gates, two granularities, one rule.)
    assert not offenders, (
        "a template/task concatenates global_password_prefix into a value — "
        "that is the REM-144 defect returning. Use a registry key + "
        "`nos_derived_secrets.<key>` (docs/secrets-p1-hkdf.md):\n  "
        + "\n  ".join(offenders)
    )
