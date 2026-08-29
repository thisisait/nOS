"""Anatomy gate — absence is counted; promised presence is enforced (2026-08-19).

The day the forge CI first ran this suite it exit-2'd on a collection error
(fastapi absent) — the ENTIRE suite had silently never run there. The cheap
fix for the environment-dependent gates would have been skipif(which(...) is
None), which is the estate's signature defect one layer up: CI goes green by
not asking. The mechanism this file pins (tests/anatomy/_environment_contract.py)
closes both directions:

  - an environment that DECLARES a tool (NOS_TEST_PROVIDES) and lacks it
    aborts the whole session before any test runs;
  - an environment that declares nothing still gets every skip counted and
    printed as its own outcome.

Retro-verification is built in: the failure branch is exercised FOR REAL on
every run (a subprocess pytest against the real conftest with a bogus
declaration must abort), so this is a gate whose red path is observed daily,
not assumed. The CI declarations themselves are pinned below so nobody goes
green by deleting the promise.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import textwrap

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ANATOMY = REPO / "tests" / "anatomy"
CHEAP_TARGET = "tests/anatomy/test_active_work_slim.py"
# A declaration that is a PATH, not a name. Both CIs must carry it or the ~150
# PHP behavioural gates run on the operator's Mac and nowhere else.
WING_VENDOR = "files/anatomy/wing/vendor/autoload.php"


def _pytest(args, env_overrides, cwd=REPO):
    env = {k: v for k, v in os.environ.items() if k != "NOS_TEST_PROVIDES"}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        capture_output=True, text=True, timeout=300, cwd=cwd, env=env,
    )


# ── the mechanism's own branches, exercised for real ────────────────────────


def test_a_broken_promise_aborts_before_any_test_runs():
    """THE failure branch: real conftest, bogus declaration → hard abort.

    This is the run that proves a runner image dropping php/jq/ansible can
    never again demote gates into skips: the same conftest that CI loads
    refuses to run a single test."""
    r = _pytest([CHEAP_TARGET, "-q"], {"NOS_TEST_PROVIDES": "nos-absent-tool-xyz"})
    assert r.returncode != 0, "a declared-but-missing tool must fail the session"
    out = r.stdout + r.stderr
    assert "ENVIRONMENT CONTRACT BROKEN" in out, out[-2000:]
    assert "nos-absent-tool-xyz" in out, "the missing tool must be NAMED"
    assert " passed" not in out, (
        "a test ran (and passed) in an environment that broke its contract — "
        "the abort must come BEFORE the first test, or a partial green leaks"
    )


def test_a_missing_declared_PATH_aborts_too():
    """The same failure branch for the OTHER kind of declaration.

    A build artifact is never on PATH, so `which` could not bind it and the
    contract had no grip on the wing vendor tree: no workflow ran `composer
    install`, and the AgentKit behavioural gates skipped 7 of 9 assertions on
    every GitHub run — measured against a `git archive` of the tree, 2026-08-29.
    """
    r = _pytest([CHEAP_TARGET, "-q"], {"NOS_TEST_PROVIDES": "files/anatomy/nope/absent.php"})
    assert r.returncode != 0, "a declared-but-missing PATH must fail the session"
    out = r.stdout + r.stderr
    assert "ENVIRONMENT CONTRACT BROKEN" in out, out[-2000:]
    assert "files/anatomy/nope/absent.php" in out, "the missing path must be NAMED"
    assert " passed" not in out, "the abort must come BEFORE the first test"


def test_a_kept_promise_runs_clean():
    """Green branch: declaring a tool that exists changes nothing."""
    r = _pytest([CHEAP_TARGET, "-q"], {"NOS_TEST_PROVIDES": "git"})
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert "environment declares it provides: git" in r.stdout


def test_undeclared_absence_is_counted_not_passed(tmp_path):
    """A skip in a promise-less environment is honest ONLY as a counted,
    printed outcome. Runs the REAL mechanism module via a re-exporting
    conftest, exactly the way tests/anatomy/conftest.py wires it."""
    (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(ANATOMY)!r})
        from _environment_contract import enforce_contract, pytest_terminal_summary  # noqa: F401
        enforce_contract()
    """))
    (tmp_path / "test_absent.py").write_text(textwrap.dedent("""\
        import pytest, shutil

        @pytest.mark.skipif(shutil.which("nos-absent-tool-xyz") is None,
                            reason="needs nos-absent-tool-xyz")
        def test_gate_that_cannot_run():
            raise AssertionError("must never execute here")

        def test_gate_that_can():
            pass
    """))
    r = _pytest(["-q", "."], {}, cwd=tmp_path)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert "absence report" in r.stdout, "the counted-absence section vanished"
    assert re.search(r"1\s*×\s*needs nos-absent-tool-xyz", r.stdout), (
        "the skipped gate was not counted by reason:\n" + r.stdout[-2000:]
    )
    assert "NOS_TEST_PROVIDES is UNSET" in r.stdout, (
        "a promise-less environment must say so next to the count"
    )


def test_the_report_prints_even_with_zero_absences(tmp_path):
    """A report that only appears on bad days is a report whose
    disappearance nobody notices."""
    (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, {str(ANATOMY)!r})
        from _environment_contract import enforce_contract, pytest_terminal_summary  # noqa: F401
        enforce_contract()
    """))
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    pass\n")
    r = _pytest(["-q", "."], {}, cwd=tmp_path)
    assert r.returncode == 0
    assert "0 gates were absent" in r.stdout


def test_the_real_conftest_carries_the_wiring():
    """The subprocess tests above prove the mechanism; this pins that the
    suite's OWN conftest still loads it (abort at import + summary hook)."""
    src = (ANATOMY / "conftest.py").read_text()
    # Anchored to column 0 — a commented-out call satisfied the plain
    # substring during this gate's own retro-verification.
    assert re.search(r"^enforce_contract\(\)", src, re.M), \
        "the import-time abort call was removed (or commented out)"
    assert "pytest_terminal_summary" in src, "the absence-report hook re-export was removed"


def test_every_php_gate_guards_the_vendor_tree():
    """A fresh worktree has no vendor/ (gitignored). Every gate that spawns
    php against the wing autoload must SKIP (counted) there, never error —
    two gates hard-failed on 2026-08-29. In CI the declaration above makes
    the same absence a session abort, so the skip certifies nothing away."""
    exempt = {
        "test_absence_is_counted.py",       # this file (strings only)
        "test_migration_promote_merge.py",  # bypasses vendor via spl_autoload_register
    }
    guard = re.compile(r"vendor/autoload\.php[\"')/ ]*\)?\.(is_file|exists)\(\)"
                       r"|AUTOLOAD\.(is_file|exists)\(\)")
    unguarded = [
        p.name for p in sorted(ANATOMY.glob("test_*.py"))
        if p.name not in exempt
        and "vendor/autoload" in (src := p.read_text(encoding="utf-8"))
        and "subprocess" in src
        and not guard.search(src)
    ]
    assert not unguarded, (
        f"{unguarded} spawn php against the wing vendor tree without an "
        "autoload existence guard — on a fresh worktree they ERROR instead of "
        "skipping with a counted reason"
    )


# ── the declarations, pinned where they live ────────────────────────────────


def _woodpecker_pytest_step() -> dict:
    doc = yaml.safe_load((REPO / ".woodpecker" / "tests.yml").read_text())
    step = doc["steps"].get("pytest-anatomy")
    assert step, ".woodpecker/tests.yml lost its pytest-anatomy step"
    return step


def test_the_forge_declares_and_installs_what_the_gates_need():
    step = _woodpecker_pytest_step()
    declared = {t.strip() for t in
                str((step.get("environment") or {}).get("NOS_TEST_PROVIDES", "")).split(",") if t.strip()}
    assert {"git", "ansible-playbook", "php", "jq", "sqlite3", WING_VENDOR} <= declared, (
        f"forge pytest step declares only {sorted(declared)} — a tool removed "
        "from the declaration is a hundred gates quietly demoted to skips on "
        "the ONLY CI the pzny branch ever reaches"
    )
    cmds = "\n".join(step.get("commands", []))
    assert ". tools/ci-freeze.env" in cmds and "$NOS_ANSIBLE_CORE" in cmds, (
        "the forge no longer installs ansible-core from the frozen pin "
        "(tools/ci-freeze.env) — the removal-ladder gates would run against "
        "whatever version drifts in, or abort on the contract"
    )
    for tool in ("php-cli", "jq", "sqlite3", "git"):
        assert tool in cmds, f"declared tooling '{tool}' has no install line — the contract would abort every run"


def test_github_pytest_job_declares_and_pins():
    doc = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
    job = doc["jobs"]["pytest"]
    declared = {t.strip() for t in str((job.get("env") or {}).get("NOS_TEST_PROVIDES", "")).split(",") if t.strip()}
    assert {"git", "ansible-playbook", "php", "composer", WING_VENDOR} <= declared, (
        f"GitHub pytest job declares only {sorted(declared)} — a runner-image "
        "update dropping a tool must go red, not demote gates to skips"
    )
    runs = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert ". tools/ci-freeze.env" in runs and "$NOS_ANSIBLE_CORE" in runs, (
        "GitHub pytest job stopped installing ansible-core from the frozen pin"
    )
    assert "composer install" in runs and "files/anatomy/wing" in runs, (
        "GitHub pytest job does not install the wing vendor tree, so the PHP "
        "behavioural gates skip here. The declaration above now aborts the "
        "session instead — put the install back rather than dropping it."
    )


def test_the_markdown_pin_is_single_sourced():
    """tools/devlog-compile.py sys.exit()s on any other markdown version
    (bundle byte-determinism). An unpinned CI install (3.10.3) failed the
    devlog gates on the forge's first-ever run, 2026-08-19. Both CI files
    must carry exactly the tool's own pin."""
    m = re.search(r'^MARKDOWN_PIN = "([\d.]+)"', (REPO / "tools" / "devlog-compile.py").read_text(), re.M)
    assert m, "MARKDOWN_PIN vanished from tools/devlog-compile.py"
    pin = m.group(1)
    for ci in (".woodpecker/tests.yml", ".github/workflows/ci.yml"):
        src = (REPO / ci).read_text()
        installs = re.findall(r"markdown==([\d.]+)", src)
        assert installs, f"{ci} no longer pins markdown — 'pip install markdown' floats and the devlog gates abort"
        assert all(v == pin for v in installs), (
            f"{ci} pins markdown=={installs} but tools/devlog-compile.py pins {pin} — the gates will abort"
        )
