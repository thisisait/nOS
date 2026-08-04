"""No npm install in this playbook may execute a package's install scripts.

MEASURED 2026-08-04, the day the ChainDrop worm ran.

443 npm packages and 2 235 versions were compromised in under four hours,
starting from `keyv@6.0.0` (153.7M weekly downloads) and spreading through
harvested GitHub maintainer credentials. The dropper runs as an INSTALL
LIFECYCLE SCRIPT: `setup.mjs` fetches the Bun runtime, and a 727KB payload then
harvests credentials across 140+ filesystem paths — npm and GitHub tokens, AWS,
Vault, Kubernetes, SSH keys, and specifically `.claude/credentials.json` — and
plants persistence in `.claude/settings.json` SessionStart hooks and
`.vscode/tasks.json`.

THIS ESTATE WAS NOT HIT, and the reason is worth stating precisely because it
is not a defence: 6 315 package.json were scanned that evening and 0 of the
2 235 malicious versions were present, because eslint pins keyv, flat-cache and
file-entry-cache below the poisoned majors. Semver luck. `--ignore-scripts` is
the same outcome deliberately: a poisoned tarball that cannot run code at
install time must wait to be imported, which is a far smaller and far more
observable window.

WHY SIGNATURE VERIFICATION WOULD NOT HAVE HELPED. The malicious releases
carried VALID SLSA provenance — the attacker pushed poisoned commits and let
the project's own release automation cryptographically attest the malware.
Provenance proves where a build came from, not that its source was authorised.
So the usual answer ("verify the signature") passes this attack, and only
install-time containment and pinning do anything.

Run this against the tree as it stood on the morning of 2026-08-04 and every
assertion fails: six install sites, none hardened, and ten global packages
declared as bare names that resolve to whatever was published minutes ago.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
SEARCH_DIRS = ("tasks", "roles", "tools")
SUFFIXES = {".yml", ".yaml", ".sh", ".j2"}

# `npm install`, `npm i`, `npm ci` — the three that execute lifecycle scripts.
#
# MATCHED AT COMMAND POSITION ONLY. The first version of this pattern matched
# the word anywhere on the line, which flagged a task NAME
# ("[pazny.cortex] npm ci (when package-lock.json changed)") and a `_comment`
# field describing what Node-RED's entrypoint does. Both are prose ABOUT an
# install, not an install — and a gate with false positives gets muted, which
# is worse than not having it. So `npm` must sit where a shell would run it:
# at the start of a line, after a shell separator, after a `cmd:`/`shell:` key,
# or as the tail of an interpreter path (`.../npm`).
_INSTALL = re.compile(
    r"""(?:^|[|;&]\s*|(?:cmd|shell)\s*:\s*|/)         # command position
        npm"?                                          # the binary, maybe quoted
        \s+(?:install|ci|i)\b""",
    re.VERBOSE,
)
_HARDENED = "ignore-scripts"


def _install_lines():
    """Yield (path, lineno, text) for every real npm install invocation."""
    for d in SEARCH_DIRS:
        root = REPO / d
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in SUFFIXES or not path.is_file():
                continue
            if "node_modules" in path.parts:
                continue
            for lineno, line in enumerate(path.read_text(
                    encoding="utf-8", errors="ignore").splitlines(), 1):
                stripped = line.strip()
                # Comments describe installs; they do not perform them.
                if stripped.startswith("#") or stripped.startswith("//"):
                    continue
                if _INSTALL.search(stripped):
                    yield path, lineno, stripped


def test_there_are_npm_installs_to_check():
    """Positive control.

    Every assertion below is vacuously true if the search finds nothing — which
    is exactly what would happen if the install tasks were renamed or moved.
    """
    found = list(_install_lines())
    assert found, (
        "no npm install invocations found under tasks/ roles/ tools/ — either "
        "they moved (update this gate) or the search pattern rotted. Either "
        "way this gate is currently proving nothing."
    )


def test_every_npm_install_is_script_hardened():
    """The defect, as the thing that must stay false."""
    unhardened = [
        f"{p.relative_to(REPO)}:{n}  {t[:90]}"
        for p, n, t in _install_lines()
        if _HARDENED not in t
    ]
    assert not unhardened, (
        "these npm invocations execute package install scripts:\n  "
        + "\n  ".join(unhardened)
        + "\n\nChainDrop's dropper IS an install script. Add "
        "`--ignore-scripts` (the tasks render it from `npm_ignore_scripts`, "
        "so it stays one switch). If a package genuinely needs its "
        "postinstall, say so at the call site — do not drop the flag "
        "estate-wide for one dependency."
    )


def test_the_hardening_switch_defaults_to_on():
    text = CONFIG.read_text(encoding="utf-8")
    m = re.search(r"^npm_ignore_scripts:\s*(\S+)", text, re.MULTILINE)
    assert m, "npm_ignore_scripts is not declared in default.config.yml"
    assert m.group(1).lower() in {"true", "yes"}, (
        f"npm_ignore_scripts defaults to {m.group(1)!r}. A default-off safety "
        f"control is a control nobody has."
    )


def test_global_npm_packages_are_pinned():
    """A bare name resolves to whatever was published minutes ago.

    That is the exact window ChainDrop lived in — 443 packages in four hours.
    StepSecurity's own mitigation is a minimum release age of 3-7 days;
    pinning is how you get that for free, and it matches this operator's
    standing rule that a version move is a proposal, never a side effect of a
    converge.
    """
    text = CONFIG.read_text(encoding="utf-8")
    m = re.search(r"^node_global_packages:\n((?:\s+-\s+.*\n)+)", text, re.MULTILINE)
    assert m, "node_global_packages is no longer a list in default.config.yml"

    unpinned = []
    for raw in m.group(1).splitlines():
        entry = raw.strip().lstrip("-").strip().strip('"').strip("'")
        if not entry:
            continue
        # A scoped package is @scope/name@version — the version is the LAST @.
        body = entry[1:] if entry.startswith("@") else entry
        if "@" not in body:
            unpinned.append(entry)

    assert not unpinned, (
        f"these global npm packages are declared without a version: {unpinned}. "
        f"Each converge therefore installs whatever is newest at that instant."
    )
