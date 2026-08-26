"""Anatomy gate: ONE `secret:` resolver, and every caller provably calls IT.

THE DEFECT THIS PINS (found 2026-08-12). The 2026-08-11 migration moved
`pulse_jobs.env_json` to `secret:<name>` references and taught exactly one
consumer — the Pulse daemon — to resolve them. The nine on-demand shell
runners kept exporting `env_json` VERBATIM, so every operator-triggered run
of a migrated job (14 of 25 that day) handed its agent the literal string
`secret:wing_api_token` and died on a 401 — at whatever model tier the job
pins, having spent the call to prove a token error.

THE SHAPE THIS REFUSES: a second implementation. Two resolvers that agree
today are the estate's oldest defect wearing a new hat (one provider list
restated six times and already disagreeing on the tail; a contract number
written twice and bumped once). So this gate does NOT test that the shell
path "behaves like" the daemon on sample inputs — it asserts that both paths
ARE `pulse/secrets.py`:

  - the daemon delegates to it (no parsing logic of its own),
  - each shell caller pipes env_json through `resolve_pulse_env_json`
    (tools/lib/pulse-env.sh) BEFORE any other use of the blob,
  - the shim contains no logic, only the `python3 -m pulse.secrets` call,
  - and the prefix-parsing exists at exactly one site in the tree.

Plus one functional check of the CLI contract itself (the half a source
grep cannot see): presence-not-truthiness, refuse-on-unknown with an EMPTY
stdout, literal passthrough, and the PHP `[]`-empty-env spelling.

Wing's PHP consumers are deliberately NOT callers: `actionRunNow` only sets
`next_fire_at` (the daemon executes), and the catalog view strips env values
entirely (`withoutSecrets`). test_anatomy_view_is_read_only.py holds that
line; if a PHP execution path ever grows, it must join this gate.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
RESOLVER = REPO / "files/anatomy/pulse/pulse/secrets.py"
DAEMON = REPO / "files/anatomy/pulse/pulse/daemon.py"
SHIM = REPO / "tools/lib/pulse-env.sh"

#: Every shell file that reads pulse_jobs.env_json for EXECUTION (measured
#: 2026-08-12; the other readers are job scripts consuming already-exported
#: vars, read-only views, and comments). A new runner belongs here the day
#: it is written — test_every_env_json_exporter_is_listed keeps that honest.
#: (Five launchers left this list in the 2026-08-26 roster close: run-scout,
#: run-remediator, run-upgrade-advisor with their retired agents; run-curator
#: and run-migration-author with the park.)
RUNNERS = [
    "tools/run-librarian.sh",
    "tools/run-phase5-ceremony.sh",
    "tools/run-surveyor.sh",
    "tools/run-upgrade-architect.sh",
]
SEED = "tools/cortex-seed-fixtures.sh"


def test_exactly_one_parsing_site() -> None:
    """The prefix-parsing logic exists once, in pulse/secrets.py.

    Scans every tracked source file for the two spellings a second
    implementation would need: defining the prefix, or testing for it.
    Emitting `"secret:name"` as a VALUE (the catalog does, 25 times) is not
    parsing and stays legal.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard",
         "*.py", "*.sh", "*.php"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    parse_pat = re.compile(
        r"""SECRET_PREFIX\s*=            # defining the prefix
          | startswith\(\s*["']secret:   # python-side test
          | str_starts_with\([^)]*secret: # php-side test
          | ==\s*["']secret:             # comparison-style test
          | \bstartswith\(\s*SECRET_PREFIX
        """,
        re.X,
    )
    offenders = []
    for rel in tracked:
        if rel.startswith("tests/"):
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        if parse_pat.search(text):
            offenders.append(rel)
    assert offenders == ["files/anatomy/pulse/pulse/secrets.py"], (
        f"`secret:` parsing found at {offenders} — the contract is ONE "
        "implementation (pulse/secrets.py) with N callers. A second copy "
        "agrees today and drifts tomorrow; delegate instead."
    )


def test_the_daemon_is_a_caller_not_an_implementation() -> None:
    src = DAEMON.read_text(encoding="utf-8")
    assert "from . import secrets as secret_refs" in src, (
        "the daemon no longer imports the shared resolver"
    )
    body = src[src.index("def _resolve_secrets"):]
    body = body[: body.index("\n    def ", 1)]
    assert "secret_refs.resolve_env(" in body, (
        "daemon._resolve_secrets stopped delegating to pulse.secrets"
    )
    assert "yaml" not in src, (
        "the daemon reads the store itself again — that read belongs to "
        "pulse.secrets.load_store (per-resolution, fail-closed)"
    )


def test_the_shim_contains_no_second_implementation() -> None:
    src = SHIM.read_text(encoding="utf-8")
    assert "python3 -m pulse.secrets" in src, (
        "tools/lib/pulse-env.sh no longer invokes the shared module"
    )
    assert "resolve_pulse_env_json()" in src, "the shim function was renamed"
    for logic in ("jq", "yaml", "sqlite3"):
        assert logic not in src, (
            f"the shim grew `{logic}` — it must stay a zero-logic shim over "
            "pulse/secrets.py, or it becomes the second implementation"
        )


def test_every_runner_resolves_before_any_other_use() -> None:
    """Order is the contract: fetch → resolve → everything else.

    A runner that resolves AFTER reading a token out of the blob pre-flights
    with the literal `secret:…` — exactly the bug, one line lower.
    """
    for rel in RUNNERS:
        lines = (REPO / rel).read_text(encoding="utf-8").splitlines()
        assert any(re.search(r"source .*lib/pulse-env\.sh", ln) for ln in lines), (
            f"{rel} does not source tools/lib/pulse-env.sh"
        )
        fetch = next(
            (i for i, ln in enumerate(lines)
             if "jq -r '.[0].env_json'" in ln), None,
        )
        assert fetch is not None, f"{rel}: env_json fetch line not found"
        later_uses = [
            i for i, ln in enumerate(lines[fetch + 1:], start=fetch + 1)
            if "JOB_ENV_JSON" in ln
        ]
        assert later_uses, f"{rel}: env blob fetched and never used?"
        first = lines[later_uses[0]]
        assert "resolve_pulse_env_json" in first, (
            f"{rel}:{later_uses[0] + 1} uses JOB_ENV_JSON before resolving "
            f"secret references: {first.strip()!r}. The resolve call must be "
            "the FIRST use after the fetch, or the pre-flight reads literals."
        )


def test_the_seed_script_resolves_through_the_shim() -> None:
    src = (REPO / SEED).read_text(encoding="utf-8")
    assert re.search(r"source .*lib/pulse-env\.sh", src), (
        f"{SEED} does not source tools/lib/pulse-env.sh"
    )
    body = src[src.index("job_env ()"):]
    body = body[: body.index("\n}") + 2]
    assert "resolve_pulse_env_json --exports" in body, (
        f"{SEED}::job_env no longer pipes env_json through the shared "
        "resolver — its exports would carry `secret:…` literals"
    )
    assert "shlex.quote" not in body, (
        f"{SEED}::job_env quotes exports itself again — that is the start "
        "of a second implementation; --exports owns the quoting"
    )


def test_every_env_json_exporter_is_listed() -> None:
    """The caller list above must not rot.

    Any tracked .sh file that both reads `env_json` and exports/evals env is
    either in RUNNERS/SEED (and therefore gated) or a job script consuming
    vars already exported for it (which never touches the blob). Keyed on the
    fetch pattern, not a hand-maintained doc.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "*.sh"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    fetchers = sorted(
        rel for rel in tracked
        if re.search(r"env_json\s+from\s+pulse_jobs|\.\[0\]\.env_json",
                     (REPO / rel).read_text(encoding="utf-8", errors="replace"))
    )
    assert fetchers == sorted(RUNNERS + [SEED]), (
        f"env_json fetchers on disk {fetchers} != gated callers. A new "
        "fetcher must source tools/lib/pulse-env.sh, resolve before use, "
        "and join the list here."
    )


def test_cli_contract() -> None:
    """The functional half: run the actual module the shim invokes.

    HOME is pointed at a temp store, so this exercises the real path
    (~/.nos/secrets.yml under $HOME) with zero mocking of the resolver.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as home:
        nos = pathlib.Path(home) / ".nos"
        nos.mkdir()
        (nos / "secrets.yml").write_text(
            "wing_api_token: tok-abc\n"
            "mail_password: ''\n",          # declared-and-EMPTY: an answer
            encoding="utf-8",
        )
        env = {**os.environ,
               "HOME": home,
               "PYTHONPATH": str(REPO / "files/anatomy/pulse")}

        def run(stdin: str, *args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, "-m", "pulse.secrets", *args],
                input=stdin, capture_output=True, text=True, env=env,
            )

        r = run(json.dumps({
            "LIT": "plain",
            "TOK": "secret:wing_api_token",
            "MAIL": "secret:mail_password",
        }))
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout) == {
            "LIT": "plain", "TOK": "tok-abc", "MAIL": "",
        }, (
            "presence-not-truthiness broke: an empty declared value must "
            "resolve to '', a literal must pass through untouched"
        )

        r = run(json.dumps({"X": "secret:not_declared"}))
        assert r.returncode == 3, "an unknown name must refuse (rc=3)"
        assert r.stdout == "", (
            "refusal leaked output — a partial env is the literal-passthrough "
            "bug with extra steps"
        )
        assert "not_declared" in r.stderr, "the refusal must NAME the fault"

        r = run("[]")
        assert (r.returncode, json.loads(r.stdout)) == (0, {}), (
            "PHP spells an empty env as [] and live rows carry it"
        )

        r = run(json.dumps({"Q": "secret:wing_api_token"}), "--exports")
        assert r.returncode == 0 and r.stdout == "export Q=tok-abc\n", r.stdout
