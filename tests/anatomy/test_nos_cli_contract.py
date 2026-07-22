"""G-5 — the real tools/nos parser honors every contract row (§8.1).

The stdin-redirect and -y-emission properties are verified by EXECUTION
against a PATH-stubbed ansible-playbook (gate-audit hole: the old source-grep
for `</dev/null` / `nos_sudo_password=''` was satisfiable by the file's own
header comment — deleting the real redirect kept the gate green while -y hung
on the vars_prompt)."""
import os, stat as statmod, subprocess
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
NOS = str(REPO / "tools/nos")

def _run(*args, env=None):
    return subprocess.run([NOS, *args], capture_output=True, text=True,
                          timeout=30, env=env)

BASE = "ansible-playbook main.yml"
V = "-e nos_cli_version=1"

ROWS = [  # args -> exact printed argv
    (["--print-cmd"],                              f"{BASE} {V}"),
    (["--print-cmd", "--tags", "keap"],            f"{BASE} --tags keap {V}"),
    (["--print-cmd", "--remove=data"],             f"{BASE} -e remove=data {V}"),
    (["--print-cmd", "--remove=none"],             f"{BASE} {V}"),           # emits NOTHING
    (["--print-cmd", "--remove=data", "--confirm"], f"{BASE} -e remove=data -e confirm=true {V}"),
    (["--print-cmd", "--remove=all", "-y", "--leave"],
     f"{BASE} -e remove=all -e confirm=true -e assume_yes=true -e nos_sudo_password= -e leave=true {V}"),
    # M1: an operator-passed sudo password suppresses the CLI's empty emission
    (["--print-cmd", "--remove=data", "-y", "-e", "nos_sudo_password=REAL"],
     f"{BASE} -e nos_sudo_password=REAL -e remove=data -e confirm=true -e assume_yes=true {V}"),
    (["--print-cmd", "-e", "blank=true"],          f"{BASE} -e blank=true {V}"),  # passthrough, no remove=none
]

def test_print_cmd_rows():
    for args, want in ROWS:
        r = _run(*args)
        assert r.returncode == 0 and r.stdout.strip() == want, (args, r.stdout)

def test_never_emits_remove_none():
    for args in (["--print-cmd"], ["--print-cmd", "--remove=none"],
                 ["--print-cmd", "-e", "blank=true"]):
        assert "remove=none" not in _run(*args).stdout

def test_never_clobbers_operator_sudo_password():
    r = _run("--print-cmd", "--remove=data", "-y", "-e", "nos_sudo_password=REAL")
    out = r.stdout.strip()
    assert "nos_sudo_password=REAL" in out
    assert not out.endswith("nos_sudo_password= " + V.split()[-1]) and \
        out.count("nos_sudo_password") == 1, (
        "-y appended an empty nos_sudo_password AFTER the operator's real one "
        "(last -e wins — the mid-wipe become failure, trace M1)")

def test_usage_errors_64():
    for args in (["--remove=DATA"], ["--remove=garbage"], ["--leave"],
                 ["--remove=data", "--confirm", "-y"], ["--remove"],
                 # O2 ordering: --remove INSIDE the passthrough is refused,
                 # not handed to ansible as an unknown flag
                 ["--tags", "iiab", "--remove=data"]):
        assert _run(*args).returncode == 64, args

def test_tags_with_remove_refused_65():
    for args in (["--remove=data", "--tags", "iiab"],
                 ["--remove=all", "-y", "--skip-tags", "stacks"]):
        assert _run(*args).returncode == 65, args

def test_yes_redirects_stdin_and_emits(tmp_path):
    # EXECUTE nos -y against a stubbed ansible-playbook: the stub reports
    # whether fd 0 is a TTY and echoes its argv. Measures the executing
    # layer — source grep was comment-satisfiable.
    stub = tmp_path / "ansible-playbook"
    stub.write_text('#!/bin/sh\nif [ -t 0 ]; then echo TTY; else echo NOTTY; fi\necho "$@"\nexit 0\n')
    stub.chmod(stub.stat().st_mode | statmod.S_IEXEC)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}",
               HOME=str(tmp_path), NOS_SRC=str(REPO))  # HOME isolation: no
    # ~/.nos/nos-cli.env override; NOS_SRC pins the cd target to the checkout.
    r = subprocess.run([NOS, "--remove=data", "-y"], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "NOTTY" in r.stdout, "-y did not redirect stdin from /dev/null (D4)"
    for tok in ("remove=data", "confirm=true", "assume_yes=true",
                "nos_sudo_password="):
        assert tok in r.stdout, f"-y execution did not pass {tok}"
