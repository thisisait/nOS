"""Anatomy gate — the post-start wiring layer may not report its own success.

roles/*/tasks/post.yml is where nOS registers OIDC clients, seeds first admins
and migrates schemas. Measured 2026-08-01: 175 `failed_when: false` against
2 `assert`/`fail` in that whole set. The doctrine is that SSO is MANDATORY, so a
400 from the Gitea Admin API reporting `ok` means a green converge over a service
that simply has no SSO — with nothing red anywhere.

THE SHARED CAUSE, across this layer and the scheduled-job layer audited the same
day: **a step records its own outcome as the fact of having ATTEMPTED, and the
record is written by the attempting code.**

WHAT THIS FILE CAN AND CANNOT DO, stated up front so nobody mistakes it for
proof of a working install:

  CAN (statically, from repo text, no host):
    1. stale-namespace `when:` — `.status`/`.json` on a var registered from
       command/shell. This is a condition that is not merely wrong but
       PERMANENTLY FALSE, so the task it guards is dead code.
    2. `changed_when: true` alongside `failed_when: false` — a recap line that
       claims an effect regardless of whether it happened.
    3. sentinel collapse — `|| echo "<v>"` in a probe whose stdout is later
       compared against that same `<v>`, so the probe's own failure reads as a
       definite answer.
    4. unconsumed tolerance — a `status_code:` list admitting 4xx/5xx where the
       registered var is never branched on afterwards.
    5. owner credential nobody reads — a file that sends an admin/owner
       password where every leg is `failed_when: false` and no assert,
       fail or failed_when reads any leg's register (n8n, 2026-09-21).

  CANNOT: whether any of it is TRUE on a live host. Whether `authentik` really
  is in `gitea admin auth list`, whether the admin row really exists, whether a
  wizard was sealed empty. This file proves the SHAPE. Runtime truth needs a
  reader against the host (`--tags verify`) and end-to-end truth needs
  `nos-smoke --strict` with the ephemeral tester identity. A gate that claimed
  otherwise would be the very defect it audits.

CI-safe: YAML + text parsing only.
"""
from __future__ import annotations

import pathlib
import re

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]

POST_FILES = sorted(REPO.glob("roles/*/tasks/post*.yml")) + sorted(
    (REPO / "tasks" / "stacks").glob("*_post.yml")
)

CMD_MODULES = ("ansible.builtin.command", "ansible.builtin.shell", "command", "shell")


def _tasks(path: pathlib.Path) -> list[dict]:
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError:
        return []
    return [t for t in (doc or []) if isinstance(t, dict)]


def _rel(p: pathlib.Path) -> str:
    return str(p.relative_to(REPO))


def _when_text(task: dict) -> str:
    w = task.get("when")
    if w is None:
        return ""
    return " ".join(str(x) for x in w) if isinstance(w, list) else str(w)


def test_the_surface_is_actually_being_read():
    """Guard the guard: a glob that matches nothing passes every case below."""
    assert len(POST_FILES) >= 20, f"only {len(POST_FILES)} post files found — glob drift?"


# ── 1. A condition that can never be true ──────────────────────────────────


def test_no_when_reads_http_fields_off_a_command_result():
    """The Gitea SSO-lockout guard — one of only TWO fail: statements in the
    whole layer — was migrated from an HTTP `uri` probe to a CLI `command` and
    kept `.status | default(0) == 200`. A command result has no `.status`, so
    that evaluates 0 == 200 and the guard could never fire. A dead safety net is
    worse than none: it is counted as coverage.
    """
    offenders = []
    for path in POST_FILES:
        tasks = _tasks(path)
        cmd_vars = {
            t["register"]
            for t in tasks
            if t.get("register") and any(m in t for m in CMD_MODULES)
        }
        for t in tasks:
            cond = _when_text(t) + " " + str(t.get("failed_when", ""))
            for var in cmd_vars:
                if re.search(rf"\b{re.escape(var)}\.(status|json)\b", cond):
                    offenders.append(
                        f"{_rel(path)}: task {t.get('name')!r} tests {var}.status/.json, "
                        f"but {var} is registered from command/shell — permanently false"
                    )
    assert not offenders, (
        "conditions that can never be true; whatever they guard is dead:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


# ── 2. A recap line that claims an effect it did not check ─────────────────

# Sites that predate the rule. Each is a real instance; the list exists so the
# gate goes green on the CURRENT tree while refusing anything NEW, rather than
# being deleted for being inconvenient. Shrinking it is the work.
# Seeded 2026-08-01 by MEASURING the tree, not by guessing (the first draft of
# this list was three files chosen from memory and was wrong in both
# directions). Counts at seed time: nextcloud 5, bookstack 3, gitea 2,
# wordpress 2, calibre_web 1. (freescout was in the first seed and is
# already clean — the staleness test below caught that within the hour.)
CHANGED_WHEN_TRUE_LEGACY = {
    "roles/pazny.nextcloud/tasks/post.yml",
    "roles/pazny.bookstack/tasks/post_migration_attempt.yml",
    "roles/pazny.gitea/tasks/post.yml",
    "roles/pazny.wordpress/tasks/post.yml",
    "roles/pazny.calibre_web/tasks/post.yml",
}


def test_no_new_task_hardcodes_changed_under_a_swallowed_failure():
    """`changed_when: true` + `failed_when: false` prints `changed` whether or
    not the thing happened — the recap actively asserts an effect nobody
    verified. `changed_when` must key off rc or an output marker."""
    offenders = []
    for path in POST_FILES:
        rel = _rel(path)
        for t in _tasks(path):
            if t.get("changed_when") is True and t.get("failed_when") is False:
                if rel in CHANGED_WHEN_TRUE_LEGACY:
                    continue
                offenders.append(f"{rel}: task {t.get('name')!r}")
    assert not offenders, (
        "new tasks reporting `changed` regardless of outcome — derive it from rc "
        "or an output marker (e.g. `'set to' in stdout`):\n  " + "\n  ".join(offenders)
    )


def test_the_legacy_list_does_not_outlive_its_reason():
    """An allowlist nobody prunes becomes a permanent blind spot."""
    stale = []
    for rel in CHANGED_WHEN_TRUE_LEGACY:
        path = REPO / rel
        if not path.is_file():
            stale.append(f"{rel} (file gone)")
            continue
        if not any(
            t.get("changed_when") is True and t.get("failed_when") is False
            for t in _tasks(path)
        ):
            stale.append(f"{rel} (clean now)")
    assert not stale, (
        "drop these from CHANGED_WHEN_TRUE_LEGACY so the gate covers them: "
        + ", ".join(sorted(stale))
    )


# ── 3. A probe whose own failure reads as a definite answer ────────────────


def test_no_probe_collapses_its_failure_into_a_meaningful_value():
    """`... || echo "0"` and then `when: var.stdout == "0"` cannot tell "the
    answer is 0" from "the probe itself failed". The two mean opposite things:
    one says the admin is missing (create it), the other says we do not know."""
    offenders = []
    for path in POST_FILES:
        text = path.read_text()
        for t in _tasks(path):
            var = t.get("register")
            if not var:
                continue
            body = " ".join(str(t.get(m, "")) for m in CMD_MODULES)
            m = re.search(r'\|\|\s*echo\s+"?([A-Za-z0-9_-]+)"?', body)
            if not m:
                continue
            sentinel = m.group(1)

            # NOT this shape: `grep -c` / `wc -l` exit non-zero on ZERO matches,
            # so `|| echo 0` compensates for the exit code and prints the value
            # the command WOULD have printed. The sentinel is the true answer,
            # not a stand-in for "we do not know". (pazny.infisical does this.)
            if sentinel == "0" and re.search(r"\b(grep\s+-[a-zA-Z]*c|wc\s+-l)\b", body):
                continue

            # NOT this shape either: a sentinel whose consumers all use it to
            # SKIP. Collapsing an unknown into "do nothing" is fail-safe; the
            # defect is collapsing an unknown into "go ahead and write".
            # (pazny.nextcloud's __NC_NOT_INSTALLED__ gates every occ call with
            # `!=`, so an unreadable Nextcloud is left alone rather than poked.)
            consumers = re.findall(
                rf"{re.escape(var)}\.stdout[^\n]*?(==|!=)[^\n]*?['\"]{re.escape(sentinel)}['\"]",
                text,
            )
            if consumers and all(op == "!=" for op in consumers):
                continue
            # Does a later condition compare this var's stdout to that sentinel?
            if re.search(
                rf"{re.escape(var)}\.stdout[^\n]*['\"]{re.escape(sentinel)}['\"]", text
            ):
                offenders.append(
                    f"{_rel(path)}: {var} falls back to {sentinel!r} on its own "
                    f"failure, and a later condition treats {sentinel!r} as the answer"
                )
    assert not offenders, (
        "probes that cannot distinguish a real answer from their own failure:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


# ── 4. A tolerance nobody consumes ─────────────────────────────────────────

# Widened codes whose registered var IS branched on afterwards are correct and
# stay out of this. These are the ones where nothing reads the result.
UNCONSUMED_TOLERANCE_LEGACY: set[str] = set()  # influxdb left 2026-11-26: its assert reads the update


def test_a_widened_status_code_must_be_branched_on():
    """Accepting 4xx/5xx is fine — deciding nothing afterwards is not.

    Jellyfin admitted 400 and 500 from POST /Startup/User and then completed the
    setup wizard gated on a DIFFERENT variable, sealing a one-shot window over a
    failed admin creation. That is the only defect in that file the playbook
    cannot repair on a re-run.
    """
    offenders = []
    for path in POST_FILES:
        rel = _rel(path)
        if rel in UNCONSUMED_TOLERANCE_LEGACY:
            continue
        # ONE list, indexed. `_tasks(path)` re-parses and returns FRESH dicts
        # every call, so an `o is not t` test across two separate calls excludes
        # nothing — the task's own `changed_when` then counted as downstream
        # consumption and the rule silently passed on its own headline case.
        tasks = _tasks(path)
        for idx, t in enumerate(tasks):
            uri = t.get("ansible.builtin.uri") or t.get("uri")
            if not isinstance(uri, dict):
                continue
            codes = uri.get("status_code") or []
            if not isinstance(codes, list):
                continue
            # A WAIT LOOP is not a tolerance. `until:` + `retries:` means the
            # accepted codes ARE the success condition — a 401 from BookStack or
            # Firefly proves the web tier answered, which is the whole point of
            # waiting. Reaching the next task IS the branch. (bookstack, firefly
            # and paperclip were all flagged by the first draft of this rule.)
            if t.get("until") is not None:
                continue

            method = str(uri.get("method", "GET")).upper()
            # IDEMPOTENCY CODES ARE NOT TOLERANCE. 404 on a DELETE means "already
            # gone" and 409 on a create means "already there" — both are the
            # desired end state, and demanding a downstream branch on them would
            # flag correct code (gitea/gitlab post-forge do exactly this).
            idempotent = set()
            if method == "DELETE":
                idempotent.add(404)
            if method in ("POST", "PUT", "PATCH"):
                idempotent.add(409)
            widened = [
                c for c in codes if isinstance(c, int) and c >= 400 and c not in idempotent
            ]
            if not widened:
                continue
            var = t.get("register")
            if not var:
                offenders.append(
                    f"{rel}: task {t.get('name')!r} accepts {widened} and does not "
                    f"even register the result"
                )
                continue
            # Consumed = it decides something: everything in another task
            # EXCEPT a human-readable message (a `set_fact` deriving a
            # decision counts, e.g. gitlab post-forge:46; a `debug: msg`
            # mentioning the variable does not). Counting the message is how
            # the first draft of this rule missed its own headline case:
            # pre-fix Jellyfin named `_jf_user` in a summary string while
            # /Startup/Complete was in fact gated on a different variable and
            # sealed the one-shot wizard anyway.
            def _decisive(o: dict) -> str:
                if "ansible.builtin.debug" in o or "debug" in o:
                    return ""
                return " ".join(
                    str(v) for k, v in o.items() if k not in ("name", "msg")
                )

            control = " ".join(_decisive(o) for j, o in enumerate(tasks) if j != idx)
            if not re.search(rf"\b{re.escape(var)}\.(status|rc|json|stdout)\b", control):
                offenders.append(
                    f"{rel}: task {t.get('name')!r} accepts {widened} but nothing "
                    f"downstream branches on {var}"
                )
    assert not offenders, (
        "a failure code counted as success and then never consulted:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )


# ── 5. An owner credential nobody reads ────────────────────────────────────
# SECURITY GATE (operator 2026-11-23, session-gate-consent (a)): an owner
# account that was never created is a security path. n8n POSTed a 404 owner
# setup behind failed_when: false for months, converge green (2026-09-21).

_URI = ("ansible.builtin.uri", "uri")
_ASSERT = ("ansible.builtin.assert", "assert")
_FAIL = ("ansible.builtin.fail", "fail")
_PW_KEY = re.compile(r"(?i)^(password|pw|newpw|new_password)$")


def _walk(tasks) -> list[dict]:
    """Every task, blocks flattened (_tasks above stops at the top level)."""
    out = []
    for t in tasks or []:
        if isinstance(t, dict):
            out.append(t)
            for k in ("block", "rescue", "always"):
                out += _walk(t.get(k))
    return out


def _sends_a_credential(t: dict) -> bool:
    uri = next((t[m] for m in _URI if isinstance(t.get(m), dict)), None)
    if uri is None:
        return False
    body = uri.get("body")
    nested = [body] + (list(body.values()) if isinstance(body, dict) else [])
    return "password" in uri or any(
        isinstance(d, dict) and any(_PW_KEY.match(str(k)) for k in d) for d in nested
    )


def _judged_text(tasks: list[dict]) -> str:
    """What decides: assert `that`/`when`, fail `when`, any failed_when. Never a msg."""
    out = []
    for t in tasks:
        a = next((t[m] for m in _ASSERT if m in t), None)
        if a is not None:
            out += [str(a.get("that") if isinstance(a, dict) else a), str(t.get("when", ""))]
        if any(m in t for m in _FAIL):
            out.append(str(t.get("when", "")))
        if t.get("failed_when") not in (None, False, True):
            out.append(str(t["failed_when"]))
    return " ".join(out)


def owner_legs_nobody_reads(path: pathlib.Path) -> list[str]:
    """The legs of a file that sends a credential, when every leg swallows its
    failure and no assert/fail/failed_when reads any leg's register."""
    try:
        tasks = _walk(yaml.safe_load(path.read_text()))
    except yaml.YAMLError:
        return []
    if not any(_sends_a_credential(t) for t in tasks):
        return []
    legs = [
        t for t in tasks
        if t.get("register") and (
            _sends_a_credential(t)
            or (t.get("no_log") is True and any(m in t for m in CMD_MODULES))
        )
    ]
    # Only a loud CREDENTIAL leg is loud about the credential (an HMAC shell is not).
    if not legs or any(_sends_a_credential(t) and t.get("failed_when") is not False for t in legs):
        return []
    judged = _judged_text(tasks)
    if any(re.search(rf"\b{re.escape(t['register'])}\b", judged) for t in legs):
        return []
    return [t["register"] for t in legs]


# Empty: the EspoCRM OIDC PUT is read by a terminal assert at the end of apps_runner post
# (operator 2026-11-26: fail at the end of the step, not at once; row espocrm-oidc-fails-at-end).
OWNER_LEG_LEGACY: set[str] = set()


def test_an_owner_credential_is_read_by_an_assert():
    """A post file that sends an owner/admin credential must let a reader judge
    it: one terminal assert over the legs' statuses (n8n post.yml is the shape)."""
    offenders = [
        f"{_rel(p)}: legs {legs} all failed_when: false, nothing asserts them"
        for p in POST_FILES
        if _rel(p) not in OWNER_LEG_LEGACY and (legs := owner_legs_nobody_reads(p))
    ]
    assert not offenders, (
        "owner/admin credential legs whose failure nobody reads — end the file in an "
        "assert over their statuses (roles/pazny.n8n/tasks/post.yml):\n  "
        + "\n  ".join(offenders)
    )


def test_the_owner_legacy_does_not_outlive_its_reason():
    stale = [rel for rel in OWNER_LEG_LEGACY if not owner_legs_nobody_reads(REPO / rel)]
    assert not stale, f"drop from OWNER_LEG_LEGACY (clean or gone now): {stale}"


def test_the_owner_rule_catches_the_n8n_shape(tmp_path):
    """Guard the guard: the pre-2026-09-21 n8n owner setup must be flagged."""
    bad = tmp_path / "post.yml"
    bad.write_text(
        "- name: setup owner\n"
        "  ansible.builtin.uri:\n"
        "    url: http://127.0.0.1:5678/api/v1/owner/setup\n"
        "    method: POST\n"
        "    body: {email: a@b, password: x}\n"
        "  register: _owner\n"
        "  failed_when: false\n"
        "- name: say so\n"
        "  ansible.builtin.debug:\n"
        "    msg: \"{{ _owner.status }}\"\n"
    )
    assert owner_legs_nobody_reads(bad) == ["_owner"]
    bad.write_text(bad.read_text() + "- ansible.builtin.assert:\n    that: _owner.status == 200\n")
    assert owner_legs_nobody_reads(bad) == []
