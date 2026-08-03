"""Anatomy gate — the `nos-loop` plugin holds no logic the engine could hold.

`docs/idea/11-agentic-loop.md` §4 says the skills "contain **no logic** — they
call the engine. That is what makes the same loop reproducible from Hermes, which
will speak to the same endpoints with no Claude in the picture."

That sentence has no teeth as prose. Markdown accretes: a threshold gets pasted
in "for convenience", a path list gets summarised "so the model doesn't have to
ask", a skill starts running `pytest` directly "because the route wasn't mounted
yet" — and then the loop means one thing under Claude Code and another under
Hermes, which is two loops, which is the drift the plugin exists to prevent.

WHAT THIS FILE CAN AND CANNOT DO, so nobody mistakes it for proof the loop works:

  CAN (statically, from repo text, no host, no network):
    1. that the plugin addresses only endpoints the contract declares, and never
       the one the contract deleted (`verdicts`);
    2. that no skill runs a judge itself or opens the ledger, bypassing the
       sandbox, the work ratchet, the pinned side-effect flags and the record;
    3. that the two loop identities stay two — each skill names only its own
       token;
    4. that engine-owned decisions (size caps, the intent enum, work ratchets)
       are not copied into skill prose, where they would drift;
    5. that the ceremony skill holds no address, token or call at all;
    6. that the frontmatter is the `.claude/skills/` schema, not the Hermes
       runtime schema (`roles/pazny.hermes/templates/skills/nos/SKILL.md.j2`),
       which is a DIFFERENT contract that happens to also live in a `SKILL.md`;
    7. constraints D (no prefix-derived credential), E (loopback only, and the
       three-times-shipped 9000-instead-of-8099 defect) and F (`${#` opens a
       Jinja comment) at the plugin's surface.

  CANNOT: whether a skill is *useful*, whether the engine answers, whether a
  verdict is honest. Runtime truth is the engine's own gates
  (`test_loop_judge_runner.py`, `test_loop_ledger.py`) and end-to-end truth is a
  replayed verdict. A gate claiming otherwise would be the defect it audits.

CI-safe: text + YAML + JSON parsing only.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
BONE = REPO / "files" / "anatomy" / "bone"
PLUGIN = REPO / ".claude" / "plugins" / "nos-loop"
CONTRACT = REPO / "docs" / "idea" / "11-agentic-loop-contract.md"

SKILL_DIRS = ("weakness-scan", "propose", "judge", "loop")
#: the three skills that actually call the engine; `loop` delegates and calls nothing
CALLING_SKILLS = ("weakness-scan", "propose", "judge")

ENGINE_DOC = PLUGIN / "ENGINE.md"


def _skill(name: str) -> pathlib.Path:
    return PLUGIN / "skills" / name / "SKILL.md"


def _plugin_files() -> list[pathlib.Path]:
    return sorted(p for p in PLUGIN.rglob("*") if p.is_file())


def _client_files() -> list[pathlib.Path]:
    """Skills + commands — everything except the single calling-convention doc."""
    out = [_skill(n) for n in SKILL_DIRS]
    out += sorted((PLUGIN / "commands").glob("*.md"))
    return out


def _frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"{path.relative_to(REPO)}: no YAML frontmatter block"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), f"{path.relative_to(REPO)}: frontmatter is not a mapping"
    return data


def _body(path: pathlib.Path) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", path.read_text(), count=1, flags=re.S)


# ── 1. shape ────────────────────────────────────────────────────────────────


def test_the_plugin_has_the_shape_the_spec_names():
    manifest = PLUGIN / ".claude-plugin" / "plugin.json"
    assert manifest.is_file(), ".claude/plugins/nos-loop/.claude-plugin/plugin.json is missing"
    data = json.loads(manifest.read_text())
    assert data.get("name") == "nos-loop", "plugin.json name must be 'nos-loop'"
    assert data.get("description"), "plugin.json needs a description"

    for name in SKILL_DIRS:
        assert _skill(name).is_file(), f"missing skill: skills/{name}/SKILL.md"

    commands = sorted((PLUGIN / "commands").glob("*.md"))
    assert len(commands) == 1, (
        "the spec asks for ONE operator-visible command; found "
        f"{[c.name for c in commands]}"
    )
    assert ENGINE_DOC.is_file(), "ENGINE.md is the single place an address may live"


def test_the_plugin_is_tracked_and_not_gitignored():
    """`.gitignore` has `.claude/*`. A plugin under it is invisible to git.

    Found live: the plugin landed in `.claude/plugins/` where `.claude/*` swallowed
    it whole — `git status` showed nothing, so it would never have been committed,
    never reached CI, and never reached the Hermes host that is supposed to run the
    same ceremony. It is exactly the reason the gate sets are committed rather than
    left in `~/.nos`: a client that lives in per-host state drifts per host.
    `!.claude/plugins/` is the negation that re-includes it.
    """
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "-v", "--", *[str(p) for p in _plugin_files()]],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:  # pragma: no cover
        raise AssertionError(
            "git is not available, so this gate cannot answer. It fails rather "
            "than skips: an unanswerable check that reports green is the defect "
            "this whole subsystem exists to detect."
        )

    assert not proc.stdout.strip(), (
        "plugin files are gitignored and would never be committed:\n  "
        + "\n  ".join(proc.stdout.strip().splitlines())
        + "\nAdd the negation to .gitignore, next to `!.claude/skills/`."
    )


# ── 2. frontmatter: the .claude/skills schema, not the Hermes one ───────────

#: keys that belong to roles/pazny.hermes/templates/skills/nos/SKILL.md.j2 — a
#: different runtime with a different contract. Mixing the two produces a file
#: that validates against neither.
HERMES_ONLY_KEYS = {"version", "author", "license", "platforms", "metadata", "prerequisites"}


def test_skill_frontmatter_is_the_claude_skills_schema():
    reference = _frontmatter(REPO / ".claude" / "skills" / "devlog" / "SKILL.md")
    assert set(reference) == {"name", "description"}, (
        "the reference skill's frontmatter shape moved; re-derive this gate from "
        ".claude/skills/devlog/SKILL.md before relaxing it"
    )

    for name in SKILL_DIRS:
        fm = _frontmatter(_skill(name))
        leaked = HERMES_ONLY_KEYS & set(fm)
        assert not leaked, (
            f"skills/{name}/SKILL.md carries Hermes-runtime frontmatter keys "
            f"{sorted(leaked)}. That is a different schema "
            "(roles/pazny.hermes/templates/skills/nos/SKILL.md.j2); do not mix them."
        )
        assert set(fm) == {"name", "description"}, (
            f"skills/{name}/SKILL.md frontmatter must be exactly name+description, "
            f"got {sorted(fm)}"
        )
        assert fm["name"] == name, (
            f"skills/{name}/SKILL.md declares name={fm['name']!r}; it must match "
            "its directory or the skill is unaddressable"
        )
        assert len(str(fm["description"]).strip()) > 40, (
            f"skills/{name}/SKILL.md needs a description that says when to use it"
        )


def test_the_command_declares_a_description():
    cmd = sorted((PLUGIN / "commands").glob("*.md"))[0]
    fm = _frontmatter(cmd)
    assert fm.get("description"), f"{cmd.name}: an operator-visible command needs a description"


# ── 3. endpoints: only what the contract declares, never what it deleted ────

_ROUTE_RE = re.compile(r"/api/v1/loop/([A-Za-z0-9_-]+)")


def _engine_routes() -> set[str]:
    """The routes that ACTUALLY EXIST, read from the engine's decorators.

    THIS FUNCTION REPLACED A DOC-DERIVED ALLOWLIST, and the reason is the whole
    subject of this repository. The previous version read the contract PROSE and
    compared it to the plugin PROSE — two files a proposal may edit — while the
    engine, the only thing that actually serves a request, was never consulted.
    An adversarial review (2026-08-03) caught it on the commit that added
    `/forget`: the route and its row in the contract's endpoint table landed
    together, so the gate was satisfied by the same change it was meant to
    judge. A gate you can satisfy by editing the gate is not one.

    Read from the AST, never a substring: a decorator inside a docstring or a
    commented-out route would otherwise count as a live endpoint.
    """
    routes: set[str] = set()
    for src in (BONE / "looproutes.py", BONE / "weaknesses.py"):
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # BOTH forms. `async def` is `AsyncFunctionDef`, a separate node
            # type, and the weakness reader's route is one — checking only
            # FunctionDef silently dropped a live endpoint from the allowlist.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                if not (isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router"):
                    continue
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        routes.update(_ROUTE_RE.findall("/api/v1/loop" + arg.value))
                        # `/judge/{job_id}` and `/judge` are one name here.
                        head = arg.value.strip("/").split("/")[0]
                        if head:
                            routes.add(head)
    return routes


def _contract_routes() -> set[str]:
    """Route names the contract PROSE declares as existing.

    No longer the allowlist — now the thing checked AGAINST the engine, so doc
    drift is caught in both directions rather than being the authority.
    """
    routes: set[str] = set()
    for line in CONTRACT.read_text().splitlines():
        if "does not exist" in line:
            continue
        routes.update(_ROUTE_RE.findall(line))
    return routes


def test_the_contract_prose_matches_the_engine():
    """Doc drift, both directions, with the CODE as the authority.

    A route the prose describes and the engine does not serve sends a model
    into a 404 it will read as "not built yet"; a route the engine serves and
    the prose omits is an undocumented surface. Neither is caught by comparing
    prose to prose.
    """
    engine, declared = _engine_routes(), _contract_routes()
    assert "verdicts" not in engine, (
        "the engine now serves a verdicts route. §3.1 deleted it on purpose: a "
        "route that accepts a result and tells writers apart by credential is a "
        "lock whose key is a header. Removing the input surface removes the class."
    )
    phantom = sorted(declared - engine)
    assert not phantom, (
        "the contract declares routes the engine does not serve: "
        + ", ".join(phantom)
        + ". Prose is not a surface; add the route or stop promising it."
    )
    undocumented = sorted(engine - declared)
    assert not undocumented, (
        "the engine serves routes the contract never mentions: "
        + ", ".join(undocumented)
        + ". §6.1's table is the operator-facing inventory of the loop's surface."
    )


def test_the_plugin_addresses_only_routes_the_engine_serves():
    declared = _engine_routes()
    assert {"weaknesses", "budget", "proposals", "judge"} <= declared, (
        "the contract's endpoint table moved; re-derive this gate from "
        "docs/idea/11-agentic-loop-contract.md §6.1"
    )
    assert "verdicts" not in declared, (
        "the contract now declares a verdicts route as existing. §3.1 deleted it "
        "on purpose: a route that accepts a result and tells writers apart by "
        "credential is a lock whose key is a header."
    )

    offenders = []
    for p in _plugin_files():
        if p.suffix not in {".md", ".json"}:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            for route in _ROUTE_RE.findall(line):
                if route not in declared:
                    offenders.append(f"{p.relative_to(REPO)}:{i}: /api/v1/loop/{route}")

    assert not offenders, (
        "the plugin addresses an endpoint the contract does not declare (or "
        "declares as deleted):\n  " + "\n  ".join(offenders)
    )


#: field names that would mean a client is supplying an outcome
VERDICT_INPUT_KEYS = ("\"result\"", "'result'", "\"verdict\"", "\"passed\"", "\"pass\":")


def test_no_plugin_file_offers_to_supply_a_verdict():
    offenders = []
    for p in _plugin_files():
        if p.suffix != ".md":
            continue
        text = p.read_text()
        for i, line in enumerate(text.splitlines(), 1):
            if not re.search(r"-d\s|--data|POST", line):
                continue
            for key in VERDICT_INPUT_KEYS:
                if key in line:
                    offenders.append(f"{p.relative_to(REPO)}:{i}: {line.strip()}")

    assert not offenders, (
        "a plugin file composes a request body carrying an outcome. You cannot "
        "forge a value you are never asked to supply — so nothing may ask:\n  "
        + "\n  ".join(offenders)
    )


# ── 4. no engine bypass ─────────────────────────────────────────────────────

#: invoking any of these directly skips the sandbox, the min_work ratchet, the
#: pinned side-effect flags and the ledger — and yields a number no other runtime
#: can reproduce.
JUDGE_BYPASS = (
    r"\bpytest\b",
    r"\bansible-lint\b",
    r"nos-smoke",
    r"genome-codegen",
    r"cortex-corpus-diff",
    r"keap-lint",
)
LEDGER_BYPASS = (r"\bsqlite3\b", r"wing\.db", r"loop_verdicts", r"loop_proposals", r"loop_judge_runs")

#: A skill may NAME a judge only to forbid running it. Prose that merely mentions
#: `pytest` while saying "never run it" is the skill doing its job; the same word
#: inside a fenced command block, or in a sentence that is not a prohibition, is
#: the skill doing the engine's. The exemption is deliberately narrow: strip the
#: prohibition and this gate goes red, which means the prohibition cannot quietly
#: soften into a suggestion.
_PROHIBITION = ("never", "do not", "does not", "must not", "bypass", "instead of")


def test_no_skill_runs_a_judge_or_opens_the_ledger_itself():
    offenders = []
    for p in _client_files():
        in_fence = False
        for i, line in enumerate(_body(p).splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            hits = [pat for pat in JUDGE_BYPASS + LEDGER_BYPASS if re.search(pat, line)]
            if not hits:
                continue
            if not in_fence and any(w in line.lower() for w in _PROHIBITION):
                continue
            where = "in a command block" if in_fence else "outside a prohibition"
            offenders.append(f"{p.relative_to(REPO)}:{i} ({where}): {line.strip()[:100]}")

    assert not offenders, (
        "a skill reaches past the engine — running a judge by hand or touching "
        "the ledger directly. Both produce a result nobody can replay:\n  "
        + "\n  ".join(offenders)
    )


# ── 5. two identities stay two ──────────────────────────────────────────────

TOKEN_OWNER = {
    "loop_propose_token": {"weakness-scan", "propose"},
    "loop_judge_token": {"judge"},
}


def test_each_skill_names_only_its_own_token():
    offenders = []
    for token, owners in TOKEN_OWNER.items():
        for name in SKILL_DIRS:
            present = token in _skill(name).read_text()
            if present and name not in owners:
                offenders.append(f"skills/{name}/SKILL.md names {token}")
            if not present and name in owners:
                offenders.append(f"skills/{name}/SKILL.md should name {token} and does not")

    assert not offenders, (
        "the proposer/evaluator split leaked. Constraint A says they never share "
        "an identity; a skill that knows both tokens has collapsed them:\n  "
        + "\n  ".join(offenders)
    )


def test_the_ceremony_holds_no_address_no_token_and_no_call():
    body = _body(_skill("loop"))
    offenders = [
        marker
        for marker in ("curl", "/api/v1/", "Bearer", "$BASE", "loop_propose_token", "loop_judge_token", "127.0.0.1")
        if marker in body
    ]
    assert not offenders, (
        "skills/loop/SKILL.md is the ceremony: it delegates every step and holds "
        f"nothing callable. Found {offenders}. Anything it does itself is "
        "something the other three skills and Hermes will each do differently."
    )


def test_the_calling_skills_point_at_the_single_calling_convention():
    for name in CALLING_SKILLS:
        assert "ENGINE.md" in _skill(name).read_text(), (
            f"skills/{name}/SKILL.md must defer to ENGINE.md for the address and "
            "the token, or the base URL ends up written down in four places and "
            "drifts in three of them"
        )


# ── 6. engine-owned decisions are not copied into skill prose ───────────────

#: values and knobs the engine owns. A skill that names one has taken a decision
#: the engine already takes — and taken it somewhere Hermes cannot see.
ENGINE_OWNED = (
    "version-pin-bump",
    "config-fix",
    "render-fix",
    "wiring-fix",
    "gate-add",
    "dependency-bump",
    "max_files",
    "max_diff_lines",
    "max_attempts",
    "min_work",
    "requires_operator",
)


def test_no_skill_restates_a_decision_the_engine_makes():
    offenders = []
    for p in _client_files():
        for i, line in enumerate(_body(p).splitlines(), 1):
            for token in ENGINE_OWNED:
                if token in line:
                    offenders.append(f"{p.relative_to(REPO)}:{i}: {token}")

    assert not offenders, (
        "a skill hard-codes an engine-owned value. Ask the engine and quote its "
        "answer; a copy here is a second source of truth that only one runtime "
        "reads:\n  " + "\n  ".join(offenders)
    )


# ── 7. constraints D, E, F at the plugin surface ────────────────────────────


def test_no_prefix_derived_credential_appears_in_the_plugin():
    offenders = []
    for p in _plugin_files():
        text = p.read_text(errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if "_pw_" in line or "global_password_prefix" in line:
                if "never" in line.lower() or "refuses" in line.lower():
                    continue  # prose may name the shape while forbidding it
                offenders.append(f"{p.relative_to(REPO)}:{i}: {line.strip()[:100]}")

    assert not offenders, (
        "constraint D: the loop's tokens are minted random, never "
        "{prefix}_pw_*. The runtime blast radius is ratcheted by "
        "tests/anatomy/test_secret_blast_radius.py:\n  " + "\n  ".join(offenders)
    )


_URL_RE = re.compile(r"https?://([A-Za-z0-9._:\-\[\]]+)")
LOOPBACK = ("127.0.0.1", "localhost", "[::1]")


def test_every_url_in_the_plugin_is_loopback():
    offenders = []
    for p in _plugin_files():
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            for host in _URL_RE.findall(line):
                if not host.startswith(LOOPBACK):
                    offenders.append(f"{p.relative_to(REPO)}:{i}: {host}")

    assert not offenders, (
        "constraint E: the loop has no routable surface. REM-144 was an "
        "unauthenticated API on the edge leaking the password prefix; a hostname "
        "here is how that starts:\n  " + "\n  ".join(offenders)
    )


def test_bones_port_is_named_once_and_is_never_wings():
    """The 8099-vs-9000 defect has shipped three times in this estate."""
    wrong = []
    named_8099 = []
    for p in _plugin_files():
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            # `:9000` is the defect (a port in an address). A bare 9000 in prose
            # is the estate explaining the defect — the same carve-out
            # test_bone_port_never_hardcoded.py makes for comments.
            if re.search(r":\s*9000\b", line):
                wrong.append(f"{p.relative_to(REPO)}:{i}: {line.strip()[:80]}")
            if "8099" in line:
                named_8099.append(p.relative_to(REPO))

    assert not wrong, (
        "9000 is Wing, not Bone. A signed request to 9000 reaches a service with "
        "no verifier, 401s, and the caller exits 0 with nothing delivered:\n  "
        + "\n  ".join(wrong)
    )
    assert set(named_8099) <= {ENGINE_DOC.relative_to(REPO)}, (
        "Bone's port is a variable (bone_port). Only ENGINE.md may carry the "
        f"documented fallback literal; found it in {sorted(set(named_8099))}"
    )


def test_the_plugin_adds_no_shell_and_no_jinja_comment_opener():
    """Constraint F — `${#` opens a Jinja comment and the RENDER fails."""
    shell = [p.relative_to(REPO) for p in _plugin_files() if p.suffix == ".sh"]
    assert not shell, (
        "the plugin ships no shell scripts; anything under a role's files/ is a "
        f"Jinja template first and a script second: {shell}"
    )
    offenders = [
        f"{p.relative_to(REPO)}:{i}"
        for p in _plugin_files()
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1)
        if "${#" in line
    ]
    assert not offenders, (
        "`${#` opens a Jinja comment; a template:-rendered file containing it "
        "fails at render, and `bash -n` will not catch it. Use ${!arr[@]} or "
        "${arr[@]+…}:\n  " + "\n  ".join(offenders)
    )


# ── 8. the honest ceiling, stated as a test so it cannot be forgotten ───────


def test_the_indeterminate_verdict_is_named_and_not_collapsed():
    """Three values, not two — in the skill that reports them."""
    body = _body(_skill("judge"))
    for value in ("pass", "fail", "indeterminate"):
        assert f"`{value}`" in body, (
            f"skills/judge/SKILL.md must name `{value}` explicitly. Collapsing "
            "indeterminate into fail teaches the loop to 'fix' code in response "
            "to a down organ; collapsing it into pass rebuilds hidden_fees/08."
        )
