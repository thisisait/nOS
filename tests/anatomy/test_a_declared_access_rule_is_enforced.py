"""`auth-default-access: deny-all` enforces nothing without an auth-file.

WHAT WAS FOUND, 2026-08-08, when the operator said "ntfy runs, I can't log in".

`roles/pazny.ntfy/templates/server.yml.j2` declared `auth-default-access:
deny-all` and no `auth-file`. ntfy enforces access only once it has a user
database, so the rule was inert. Measured against the running container:

    POST http://127.0.0.1:2586/nos-info        -> 200   (anonymous publish)
    GET  http://127.0.0.1:2586/nos-info/json   -> 200   (anonymous SUBSCRIBE)
    docker exec iiab-ntfy-1 ntfy user list
        option database-url or auth-file not set; auth is unconfigured

Every notification the estate sends was readable by anything that could reach
the port. The declaration read like a control and was decoration.

THE SECOND HALF IS THE MORE FAMILIAR DEFECT. `tasks/post.yml` ran
`ntfy user add` on every converge. That command fails with the same
"unconfigured" message; `2>/dev/null` discarded it and `changed_when` searched
for 'added' / 'changed password', words that never appeared. The task was green
and not-changed for as long as it had existed, and the task after it printed
`Admin user: admin / (in ~/.nos/secrets.yml)` — instructions for an account that
was never created. That is why the login failed: forward-auth was only the
second lock.

WHAT THIS GATE PINS

1. A declared `auth-default-access` requires an `auth-file` in the same file —
   the two are one control and only look like two settings.
2. The user-provisioning task is followed by an INDEPENDENT read
   (`ntfy user list`) that can fail the play. A provisioning step verified by
   its own exit code is the estate's oldest defect, and this instance survived
   months of green converges.
3. The publisher credential is separate from admin. An unattended dispatcher
   holding an admin password is a blast radius nobody chose.

WHAT IT CANNOT PIN: that the ACL is correct at runtime, or that the operator's
phone can subscribe. Those need the live server; `--tags verify` and a real
converge own them.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER_TPL = REPO / "roles/pazny.ntfy/templates/server.yml.j2"
POST = REPO / "roles/pazny.ntfy/tasks/post.yml"
CREDS = REPO / "default.credentials.yml"
WING_PLUGIN = REPO / "files/anatomy/plugins/wing-base/plugin.yml"


def test_deny_all_is_backed_by_an_auth_file():
    src = SERVER_TPL.read_text(encoding="utf-8")
    if "auth-default-access" not in src:
        return  # no access rule declared: nothing to enforce, nothing to lie about
    assert re.search(r"^\s*auth-file:", src, re.M), (
        "server.yml.j2 declares auth-default-access with no auth-file. ntfy "
        "enforces NOTHING without a user database — the rule reads like a "
        "control and is decoration. Measured on 2026-08-08: anonymous publish "
        "AND subscribe both returned 200 under a declared deny-all."
    )


def test_user_provisioning_is_verified_by_a_reader():
    src = POST.read_text(encoding="utf-8")
    assert "ntfy user list" in src, (
        "nothing in post.yml independently confirms the users exist. The "
        "provisioning command reported success for months while creating "
        "nothing; only a separate read can tell 'it worked' from 'it ran'."
    )
    verify = src[src.find("ntfy user list") - 700 : src.find("ntfy user list") + 700]
    assert "failed_when" in verify, (
        "the `ntfy user list` step does not fail the play on a missing user. A "
        "verification that cannot go red is a second success marker."
    )


def test_the_swallowing_shell_redirect_is_gone():
    """`2>/dev/null` is what turned a hard error into a green task."""
    src = POST.read_text(encoding="utf-8")
    user_add = [ln for ln in src.splitlines() if "ntfy user add" in ln]
    assert user_add, "the user-provisioning task disappeared entirely"
    for line in user_add:
        assert "2>/dev/null" not in line, (
            "`ntfy user add` still discards stderr. That is precisely how "
            '"auth is unconfigured for this server" became invisible.'
        )


def test_no_ntfy_write_runs_when_the_state_is_already_right():
    """A running ntfy owns its auth DB's write lock. Only write what is missing.

    THIS GATE PREVIOUSLY DEMANDED THE OPPOSITE, and was wrong for about an hour
    (2026-08-08). It required `retries`, on the diagnosis that
    `database is locked` was transient contention — the shape of the wing.db
    busyTimeout fix from July. Measured properly, it is not transient:

        $ docker exec iiab-ntfy-1 ntfy access nos-publisher "nos-*" write-only
        database is locked            # 5 of 5 attempts, and would be 500 of 500
        $ docker exec iiab-ntfy-1 ntfy user list
        user admin (role: admin, tier: none)      # reads are unaffected

    A running ntfy server holds the WRITE lock for its whole lifetime. Retrying
    a write that cannot succeed only fails the play more slowly. The converge
    that DID provision the accounts succeeded because its config probe failed
    first and restarted the container — the CLI slipped in before the server
    re-acquired the lock. Luck, wearing the shape of a working task.

    So the invariant is: read the state, write only what is absent. Steady state
    performs zero writes and the lock stops mattering; a first install writes
    against a fresh DB with a just-started server, which is when it works.

    KNOWN COST, stated because a skip can hide a real need: a password CHANGE
    does not propagate on a plain converge, since the user exists and is
    skipped. Restart ntfy first if one must land.
    """
    import yaml as _yaml

    doc = _yaml.safe_load(POST.read_text(encoding="utf-8"))
    offenders = []
    for task in doc or []:
        blob = str(task.get("ansible.builtin.command", "")) + str(
            task.get("ansible.builtin.shell", ""))
        if "ntfy user" not in blob and "ntfy access" not in blob:
            continue
        if "user list" in blob:
            continue  # a read cannot be blocked and needs no guard
        conds = task.get("when") or []
        conds = conds if isinstance(conds, list) else [conds]
        joined = " ".join(str(c) for c in conds)
        if "_ntfy_state" not in joined:
            offenders.append(task.get("name", "<unnamed>"))
    assert not offenders, (
        "ntfy CLI WRITE(s) that run without consulting the current state:\n  "
        + "\n  ".join(offenders)
        + "\n\nA running ntfy server holds the auth database's write lock for "
        "its lifetime, so an unconditional write fails every converge once the "
        "estate is provisioned. Guard it on `_ntfy_state.stdout` — and do not "
        "reach for `retries`: that was tried, and a write that cannot succeed "
        "does not succeed five times more slowly."
    )
    assert any(
        "user list" in (str(t.get("ansible.builtin.command", "")))
        for t in (doc or [])
    ), "nothing reads the ntfy state, so the guards above have nothing to read"


def test_the_publisher_is_not_the_admin():
    creds = CREDS.read_text(encoding="utf-8")
    assert "ntfy_publisher_user" in creds and "ntfy_publisher_password" in creds, (
        "no separate publisher credential is declared. The unattended "
        "dispatcher would hold the ntfy admin password."
    )
    plugin = WING_PLUGIN.read_text(encoding="utf-8")
    assert "NTFY_PUBLISH_USER" in plugin, (
        "the dispatch job carries no ntfy identity, so it publishes "
        "anonymously — which works only while auth is unconfigured, i.e. only "
        "while the defect this file documents is present."
    )
    assert "ntfy_admin_password" not in plugin, (
        "the dispatch job is being handed the ntfy ADMIN credential. It needs "
        "write on nos-* and nothing else."
    )
