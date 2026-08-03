"""Anatomy gate — the weakness reader's SHAPE and its wiring across four files.

Division of labour, per the doctrine this estate wrote after v0.10-beta:
**pytest owns the shape, `--tags verify` owns the effect, `nos-smoke --strict`
owns end-to-end truth.** So:

  CAN (statically, from repo text, no host, no import):
    1. the reader is actually MOUNTED — a route in a module nobody loads is the
       "daemon four converges older than its code" shape;
    2. the reader WRITES NOTHING: no file writes, and the only subprocesses it
       may spawn are read-only `git` plumbing;
    3. it exposes no route that ACCEPTS anything but filters;
    4. its two tokens are not prefix-derived, are minted lazily, are persisted,
       and reach BOTH service managers (constraint D);
    5. it adds no edge surface (constraint E);
    6. every machine-written path it watches still exists (otherwise a rename
       silently retires the alarm);
    7. it adds no shell script, so `${#…}` cannot break a Jinja render
       (constraint F).

  CANNOT: whether the reader returns the right weaknesses on a live host.
  That is tests/bone_loop/, which runs it against a synthetic git repo. A gate
  claiming otherwise would be the decoration constraint C forbids.

CI-safe: text + YAML parsing only.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

READER = REPO / "files" / "anatomy" / "bone" / "weaknesses.py"
LOOPAUTH = REPO / "files" / "anatomy" / "bone" / "loopauth.py"
BONE_MAIN = REPO / "files" / "anatomy" / "bone" / "main.py"
CREDENTIALS = REPO / "default.credentials.yml"
MAIN_YML = REPO / "main.yml"
SECRETS_TPL = REPO / "templates" / "secrets.yml.j2"
BONE_PLIST = REPO / "roles" / "pazny.bone" / "templates" / "bone.plist.j2"
BONE_TASKS = REPO / "roles" / "pazny.bone" / "tasks" / "main.yml"
MANIFEST = REPO / "state" / "manifest.yml"
TRAEFIK_VARS = REPO / "roles" / "pazny.traefik" / "vars" / "main.yml"

LOOP_TOKENS = ("loop_propose_token", "loop_judge_token", "loop_operator_token")


@pytest.fixture(scope="module")
def reader_src() -> str:
    return READER.read_text(encoding="utf-8")


# ── 1. mounted ──────────────────────────────────────────────────────────────


def test_the_reader_is_mounted_on_bones_app():
    """A router nobody includes is a route that does not exist. This estate has
    shipped that exact shape before (a daemon four converges older than its
    code), so the mount is gated, not assumed."""
    src = BONE_MAIN.read_text(encoding="utf-8")
    assert "import weaknesses as _nos_weaknesses" in src
    assert "app.include_router(_nos_weaknesses.router)" in src, (
        "weaknesses.py defines a router; main.py must include it or the reader "
        "is unreachable while every test of it still passes"
    )


def test_the_reader_is_gated_on_the_loop_scope(reader_src):
    assert 'require_loop_scope("read")' in reader_src, (
        "the reader must be behind the loop scope, not open on loopback"
    )


# ── 2. the reader writes nothing ────────────────────────────────────────────

#: Verbs that mutate. A reader that can write can be steered into writing.
#
# NOTE `.replace(` is deliberately ABSENT: `str.replace` and
# `datetime.replace` are read-only and both are used here, so including it
# would make the gate fire on correct code — and a gate that cries wolf gets
# deleted. `os.replace` (the mutating one) is listed explicitly instead.
WRITE_VERBS = (
    ".write_text(", ".write_bytes(", ".mkdir(", ".unlink(", ".rmdir(",
    ".touch(", ".rename(", "os.remove", "os.rename", "os.replace", "shutil.",
    "INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ",
)


def test_the_reader_contains_no_write_verb(reader_src):
    """It reads sources that already exist. Anything it could mutate is a
    source some other reader trusts."""
    body = "\n".join(
        line for line in reader_src.splitlines() if not line.lstrip().startswith("#")
    )
    found = [v for v in WRITE_VERBS if v in body]
    assert not found, (
        f"weaknesses.py contains write verb(s) {found}. The weakness reader is "
        "read-only by contract — a reader that mutates its own sources produces "
        "the evidence it later reports."
    )


#: `git` subcommands the reader may run. Every one is read-only; `add`,
#: `commit`, `checkout`, `clean`, `reset` are absent on purpose.
GIT_READ_ONLY = {"rev-parse", "status", "diff", "log", "show", "ls-files"}


def test_the_reader_spawns_only_read_only_git(reader_src):
    """Bone already shells out (`run-tag` runs ansible-playbook), so subprocess
    is not a new capability class here — but the READER's slice of it is git
    plumbing and nothing else."""
    # The single subprocess site is _git(); everything else must go through it.
    run_sites = re.findall(r"subprocess\.(run|Popen|call|check_output)\(", reader_src)
    assert len(run_sites) == 1, (
        f"expected exactly one subprocess site (the _git helper), found {run_sites}"
    )
    assert re.search(r'\["git", "-C", str\(root\), \*args\]', reader_src), (
        "the one subprocess site must be list-form `git -C <root> …` (shell=False)"
    )

    subcommands = set(re.findall(r'_git\(\s*(?:root|repo_root\(\)),\s*"([a-z-]+)"', reader_src))
    assert subcommands, "no _git call sites found — has the helper been renamed?"
    assert subcommands <= GIT_READ_ONLY, (
        f"weaknesses.py invokes non-read-only git subcommand(s): "
        f"{sorted(subcommands - GIT_READ_ONLY)}"
    )


# ── 3. no route accepts anything but filters ────────────────────────────────


def test_the_reader_exposes_no_mutating_route(reader_src):
    for verb in ("post", "put", "patch", "delete"):
        assert f"@router.{verb}(" not in reader_src, (
            f"the weakness reader must expose no @router.{verb} route; it reads"
        )


def test_no_route_parameter_can_influence_a_weakness(reader_src):
    """Constraint A's shape, one layer down from the verdict: nothing a caller
    sends may set a severity, a title or an evidence field. The route takes
    FILTERS — `top`, `source`, `min_severity` — and nothing else."""
    assert "Body(" not in reader_src, "a GET reader has no request body"

    route = reader_src.split("@router.get(\"/weaknesses\")", 1)[1]
    signature = route.split(")\nasync def", 1)[0] if ")\nasync def" in route else route
    signature = route[: route.index("):")]
    params = set(re.findall(r"^\s{4}(\w+)\s*[:=]", signature, re.MULTILINE))
    assert params <= {"top", "source", "min_severity", "_caller"}, (
        f"unexpected route parameter(s): {sorted(params - {'top', 'source', 'min_severity', '_caller'})}. "
        "Only filters may be accepted — an input that reaches a weakness's "
        "severity is an input that can make the estate look healthy."
    )


# ── 4. constraint D: the loop tokens (three since the §6.2 operator exit) ───


def test_loop_tokens_are_not_prefix_derived():
    """`{prefix}_pw_{svc}` is CONCATENATION: the rendered value contains the
    master in clear, so one leak yields every sibling (REM-144). The runtime
    blast radius is ratcheted at 86 by test_secret_blast_radius.py and the loop
    must not add to it."""
    text = CREDENTIALS.read_text(encoding="utf-8")
    for token in LOOP_TOKENS:
        m = re.search(rf"^{token}:\s*(.*)$", text, re.MULTILINE)
        assert m, f"{token} is not declared in default.credentials.yml"
        assert "global_password_prefix" not in m.group(1), (
            f"{token} is prefix-derived. Declare it empty and mint it in "
            "main.yml's lazy-regenerate group (constraint D)."
        )


def test_loop_tokens_are_minted_random_and_persisted():
    main = MAIN_YML.read_text(encoding="utf-8")
    secrets = SECRETS_TPL.read_text(encoding="utf-8")
    for token in LOOP_TOKENS:
        assert re.search(rf"^\s+{token}:.*openssl rand -hex 32", main, re.MULTILINE), (
            f"{token} must be minted in main.yml's lazy-regenerate group"
        )
        assert f"{token}: \"{{{{ {token}" in secrets, (
            f"{token} must be persisted to ~/.nos/secrets.yml, or every run "
            "mints a new one and the identity split becomes an outage"
        )


def test_loop_tokens_reach_both_service_managers():
    """macOS renders a plist, Linux renders a systemd --user unit, and the role
    file itself says 'keep the two in sync until they share one source'. An env
    var added to one and not the other is a Linux host whose loop 503s while
    every test passes.

    RETRO-VERIFY NOTE: the first version of this test used substring checks
    (`env_var in plist`), and renaming the key to `BONE_LOOP_JUDGE_TOKEN_DISABLED`
    kept it GREEN — the old name is a substring of the new one. It was caught by
    tools/retro-verify-weakness-reader.py as DECORATION. These assertions now
    pin the KEY-to-VALUE pairing, which is the thing that actually has to hold.
    """
    plist = BONE_PLIST.read_text(encoding="utf-8")
    tasks = BONE_TASKS.read_text(encoding="utf-8")
    for env_var, token in (
        ("BONE_LOOP_PROPOSE_TOKEN", "loop_propose_token"),
        ("BONE_LOOP_JUDGE_TOKEN", "loop_judge_token"),
        ("BONE_LOOP_OPERATOR_TOKEN", "loop_operator_token"),
    ):
        assert re.search(rf"<key>{env_var}</key>\s*<string>\{{\{{\s*{token}\b", plist), (
            f"bone.plist.j2 must render <key>{env_var}</key> from {{{{ {token} }}}}"
        )
        assert re.search(rf"'{env_var}':\s*{token}\b", tasks), (
            f"'{env_var}' must map to {token} in the Linux systemd --user env "
            "(roles/pazny.bone/tasks/main.yml) — the plist and the unit are two "
            "hand-maintained copies of one env"
        )


def test_the_runtime_refuses_a_derived_token_too():
    """The declaration gate above and this one are deliberately separate. The
    blast-radius file's own kept lesson: MEASURE THE RUNTIME VALUE, NOT THE
    DECLARATION — an operator can still put a derived value in credentials.yml."""
    src = LOOPAUTH.read_text(encoding="utf-8")
    assert 'DERIVED_MARKER = "_pw_"' in src
    assert "if DERIVED_MARKER in token:" in src, (
        "loopauth must drop a `_pw_`-shaped token as UNCONFIGURED"
    )


# ── 5. constraint E: no edge surface ────────────────────────────────────────


def test_the_loop_adds_no_manifest_entry():
    """A `state/manifest.yml` row with domain_var + port_var auto-derives a
    Traefik router. REM-144 was exactly that: a loopback bind that was real and
    irrelevant because the edge proxied around it, leaking the password prefix."""
    manifest = MANIFEST.read_text(encoding="utf-8")
    for needle in ("id: loop", "loop_domain", "loop_port", "weakness"):
        assert needle not in manifest, (
            f"'{needle}' appears in state/manifest.yml — the loop must add no "
            "routable surface; it lives inside Bone, which is already loopback"
        )


def test_bone_remains_in_the_traefik_skip_list():
    """The reader's whole constraint-E argument is 'it lives in Bone, and Bone
    is already off the edge'. If that stops being true, this must go red."""
    vars_text = TRAEFIK_VARS.read_text(encoding="utf-8")
    m = re.search(r"^traefik_skip_ids:\s*(\[[^\]]*\]|(?:\n\s+-\s*\S+)+)", vars_text, re.MULTILINE)
    assert m, "traefik_skip_ids not found in roles/pazny.traefik/vars/main.yml"
    assert re.search(r"\bbone\b", m.group(1)), (
        "bone left traefik_skip_ids — the loop reader is now reachable from the "
        "edge, and its argument for living in Bone no longer holds"
    )


def test_the_reader_binds_nothing_of_its_own(reader_src):
    src = reader_src + LOOPAUTH.read_text(encoding="utf-8")
    assert "0.0.0.0" not in src
    assert "uvicorn.run" not in src, "the reader mounts on Bone's app; it opens no port"


# ── 6. the watched paths still exist ────────────────────────────────────────


def test_every_machine_written_path_still_exists(reader_src):
    """The alarm is keyed on literal paths. Rename `nos_entity.py` and the
    reader silently stops noticing that genome-codegen's output is uncommitted —
    a gate that fails open. This is the ratchet against that."""
    block = reader_src.split("MACHINE_WRITTEN: dict[str, str] = {", 1)[1].split("}", 1)[0]
    paths = re.findall(r'^\s*"([^"]+)":', block, re.MULTILINE)
    assert len(paths) >= 10, f"expected the full machine-written set, found {len(paths)}"

    missing = [p for p in paths if not (REPO / p).exists()]
    assert not missing, (
        f"MACHINE_WRITTEN names path(s) that no longer exist: {missing}. Either "
        "the file moved (update the map) or the job stopped writing it (drop the "
        "entry) — leaving it is an alarm wired to nothing."
    )


def test_the_declared_sources_match_the_readers(reader_src):
    order = re.search(r"SOURCE_ORDER: tuple\[str, \.\.\.\] = \(([^)]*)\)", reader_src)
    required = re.search(r"SOURCE_REQUIRED: dict\[str, bool\] = \{([^}]*)\}", reader_src)
    assert order and required
    names = set(re.findall(r'"([^"]+)"', order.group(1)))
    req_names = set(re.findall(r'"([^"]+)":', required.group(1)))
    assert names == req_names, (
        f"SOURCE_ORDER and SOURCE_REQUIRED disagree: {names ^ req_names}. A source "
        "with no required-flag would decide its own absence severity."
    )
    assert names, "no sources declared"


def test_every_source_declares_a_freshness_basis(reader_src):
    """A source that returned a report without a basis could not be marked
    self-reported, which is requirement 2."""
    readers = re.findall(r"^def (_source_\w+)\(", reader_src, re.MULTILINE)
    assert len(readers) == 5, f"expected 5 source readers, found {readers}"
    for fn in readers:
        body = reader_src.split(f"def {fn}(", 1)[1].split("\n# ──", 1)[0]
        assert "Freshness(" in body and "basis=" in body, (
            f"{fn} builds a SourceReport without declaring a freshness basis"
        )


# ── 7. constraint F ─────────────────────────────────────────────────────────


def test_the_loop_added_no_shell_script():
    """`${#arr[@]}` in a `.sh` under roles/*/files/ is a JINJA COMMENT OPEN, so
    the RENDER fails — and `bash -n` never sees it. The engine and its client
    are Python precisely so this cannot happen; the gate pins that."""
    shell = [
        p for p in REPO.glob("roles/*/files/**/*.sh")
        if "BONE_LOOP" in p.read_text(encoding="utf-8", errors="replace")
        or "loop_propose_token" in p.read_text(encoding="utf-8", errors="replace")
    ]
    assert not shell, (
        f"the loop grew a shell script: {[str(p) for p in shell]}. If one is ever "
        "needed, use ${!arr[@]} or ${arr[@]+…} — never ${#…}, not even in a comment."
    )
