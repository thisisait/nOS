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
UNCONSUMED_TOLERANCE_LEGACY = {
    "roles/pazny.influxdb/tasks/post.yml",
}


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
