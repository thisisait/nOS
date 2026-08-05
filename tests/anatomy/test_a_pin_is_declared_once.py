"""A version pin lives in one file, because the second copy cannot be reached.

WHAT THE SHADOW WAS. `default.config.yml` is a `vars_files` entry and
`roles/pazny.*/defaults/main.yml` is a role default, so on every run the config
value wins — always, without exception. 38 services declared the same pin in
both places, which meant 38 lines an operator could edit, review, approve and
commit while the estate went on running the other value.

IT WAS NOT THEORETICAL. Measured 2026-08-05, five of the 38 pairs already
DISAGREED, and `docker ps` settled which side was real every time:

    role default          default.config.yml     live container
    ------------------    -------------------    ------------------------
    uptime_kuma  "1"      "2.2.1"                louislam/uptime-kuma:2.2.1
    paperclip    latest   sha-b9a80dc            …/paperclip:sha-b9a80dc
    qgis         LTR      latest                 kartoza/qgis-server:latest
    wordpress    6.9.4-…  6.9.4                  wordpress:6.9.4
    calibreweb   0.6.26-… 0.6.26                 …/calibre-web:0.6.26

Five natural experiments, five times the role default lost. That is also the
empirical proof of the precedence rule this gate rests on — stronger than
reading the docs, because it is the running estate.

The class had already reached production twice (memory `version-pins-default-
config-shadow`): an n8n RCE survived a bump applied to the dead half, and the
Kuma 1→2 major moved without its post-start automation, so the installer served
200 and healthy for ten days with zero monitors configured.

WHY THIS MATTERS MORE NOW. `version-pin-bump` is one of six intent classes the
agentic loop may propose, and both `roles/` and `default.config.yml` are inside
its §5.3 allowed roots. With one declaration, a proposal that bumps the pin
bumps THE pin. With two, "bump both halves" is a convention, and a convention is
what a proposer is worst at.

WHAT IS STILL ALLOWED. A pin that lives ONLY in a role default is fine — 17 do,
and they are not shadowed by anything. This gate forbids the pair, not the role
default.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "default.config.yml"
#: `_repo_ref` is in here because keap_repo_ref is a pin in every sense that
#: matters: it selects the source tree a service is built from.
KEY = r"[a-z0-9_]+_(?:version|image_version|image_tag|repo_ref)"


def _declared(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(rf"^({KEY}):\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).split("#")[0].strip()
    return out


def _config() -> dict[str, str]:
    return _declared(CONFIG.read_text(encoding="utf-8"))


def _role_defaults() -> dict[str, tuple[str, str]]:
    out = {}
    for path in sorted(REPO.glob("roles/pazny.*/defaults/main.yml")):
        for key, value in _declared(path.read_text(encoding="utf-8")).items():
            out[key] = (value, str(path.relative_to(REPO)))
    return out


def test_the_inputs_are_readable():
    """Positive control — an empty read makes the assertion below vacuous."""
    config = _config()
    assert len(config) > 30, (
        f"only {len(config)} pins parsed out of default.config.yml; the pattern "
        f"has stopped matching and this gate is blind"
    )
    assert _role_defaults(), "no role defaults parsed at all"


def test_no_pin_is_declared_in_both_places():
    config = _config()
    shadowed = {k: v for k, v in _role_defaults().items() if k in config}
    assert not shadowed, (
        "these role defaults are unreachable — `vars_files` outrank role "
        "defaults, so default.config.yml wins on every run and editing the line "
        "below changes nothing while looking like a fix:\n"
        + "\n".join(
            f"  {key:32} role={value[0]:<26} config={config[key]:<26} {value[1]}"
            for key, value in sorted(shadowed.items())
        )
        + "\n\nDelete the role-default line. Keep any rationale by moving it into "
          "the default.config.yml comment — that is the one a reader will find."
    )


def test_the_config_comments_do_not_point_at_a_deleted_line():
    """A pointer outlives what it pointed at, and then it misleads.

    default.config.yml's superset comment read "see roles/pazny.superset/
    defaults/main.yml (non-dev image lacks psycopg2)" — a reference to the very
    line this change removes. The rationale moved up with the pin; nothing else
    may still send a reader to a role default for a version.
    """
    text = CONFIG.read_text(encoding="utf-8")
    dangling = []
    for line in text.splitlines():
        head, _, comment = line.partition("#")
        if re.match(rf"^({KEY}):", head) and "roles/pazny." in comment and "defaults/main.yml" in comment:
            dangling.append(line.strip()[:120])
    assert not dangling, (
        "a pin comment sends the reader to a role default for the rationale, and "
        "that file no longer declares the pin:\n  " + "\n  ".join(dangling)
    )
