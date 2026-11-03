"""An agent's bash-read-only tool neither runs code nor writes, nor reads the estate's secrets.

THE HOLE (security review 2026-11-03). guardArgs() blocked a few exec flags of git and no
subcommand: `git config --global core.fsmonitor <cmd>` wrote the operator's ~/.gitconfig (HOME
is passed through) and the next `git status` anywhere ran <cmd> as the operator. `rg --pre <cmd>`
ran a program directly; `tree -o` and `git diff --output` wrote files; `cat ~/.nos/secrets.yml`
handed every bearer to a model that also reads untrusted KEAP records.

THE CHECK. Runs the real tool under PHP with HOME and NOS_REPO_ROOT in a temp dir: each attack is
refused or inert (no marker file, no ~/.gitconfig), and git status / log / cat in the repo still
work. The A14.1 source greps (test_security_agentkit_a141.py) never ran the tool.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "files/anatomy/wing/app/AgentKit"

HARNESS = r"""<?php
foreach (['LLMClient/ToolSchema.php', 'Tools/ToolInterface.php', 'Tools/ToolResult.php',
          'Tools/ToolContext.php', 'Tools/BashReadOnlyTool.php'] as $f) { require $argv[1] . '/' . $f; }
$tool = new App\AgentKit\Tools\BashReadOnlyTool();
$ctx = new App\AgentKit\Tools\ToolContext('s', 't', 'tr', 'sp', 'agent:test', 'tu');
$out = [];
foreach (json_decode(file_get_contents($argv[2]), true) as $name => $in) {
    $r = $tool->execute($in, $ctx);
    $out[$name] = ['error' => $r->isError, 'content' => $r->content];
}
echo json_encode($out);
"""


def _php() -> list[str] | None:
    if shutil.which("php"):
        return [shutil.which("php")]
    if shutil.which("frankenphp"):
        return [shutil.which("frankenphp"), "php-cli"]
    return None


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    php = _php()
    if php is None or not shutil.which("git"):
        pytest.skip("php (or frankenphp) and git are needed to run the tool")
    tmp = tmp_path_factory.mktemp("bashro")
    # As live: the checkout agents read is ~/.nos/estate, beside the secrets they must not read.
    home = tmp / "home"
    repo = home / ".nos/estate"
    repo.mkdir(parents=True)
    (home / ".nos/secrets.yml").write_text("wing_api_token: not-a-real-token\n")
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], env=env, check=True, capture_output=True)
    git("init", "-q")
    (repo / "README").write_text("hello\n")
    git("-c", "user.email=t@t", "-c", "user.name=t", "add", "README")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    marker = tmp / "pwned"
    # A repo-local fsmonitor, as a mounted or cloned repo can carry: git status must not run it.
    git("config", "core.fsmonitor", f"touch {marker}")
    (repo / "secret-link").symlink_to(home / ".nos/secrets.yml")
    cases = {
        "global_config": {"verb": "git", "args": ["config", "--global", "core.fsmonitor", f"touch {marker}"]},
        "status": {"verb": "git", "args": ["status", "--short"]},
        "log": {"verb": "git", "args": ["log", "-1", "--format=%s"]},
        "log_dash_c": {"verb": "git", "args": ["-C", str(repo), "log", "-1", "--format=%s"]},
        "dash_c_secrets": {"verb": "git", "args": ["-C", str(home / ".nos"), "status"]},
        "diff_output": {"verb": "git", "args": ["diff", f"--output={tmp}/written"]},
        "rg_pre": {"verb": "rg", "args": ["--pre", "touch", "hello", "README"]},
        "tree_out": {"verb": "tree", "args": ["-o", f"{tmp}/written2", "."]},
        "cat_readme": {"verb": "cat", "args": ["README"]},
        "cat_estate_abs": {"verb": "cat", "args": [str(repo / "README")]},
        "cat_secrets": {"verb": "cat", "args": [str(home / ".nos/secrets.yml")]},
        "cat_secrets_tilde": {"verb": "grep", "args": ["token", "-r", str(home / ".nos")]},
        "cat_link": {"verb": "cat", "args": ["secret-link"]},
    }
    (tmp / "cases.json").write_text(json.dumps(cases))
    (tmp / "h.php").write_text(HARNESS)
    run_env = {**env, "NOS_REPO_ROOT": str(repo)}
    p = subprocess.run([*php, str(tmp / "h.php"), str(TOOLS), str(tmp / "cases.json")],
                       env=run_env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    return {"out": json.loads(p.stdout), "marker": marker, "home": home, "tmp": tmp}


def test_git_cannot_write_its_config_or_run_an_fsmonitor(results):
    out = results["out"]
    assert out["global_config"]["error"], out["global_config"]
    assert not (results["home"] / ".gitconfig").exists(), "git config --global wrote ~/.gitconfig"
    assert not results["marker"].exists(), "a configured core.fsmonitor ran: code execution"


def test_no_verb_writes_a_file_or_runs_a_program(results):
    out = results["out"]
    for case in ("diff_output", "rg_pre", "tree_out"):
        assert out[case]["error"], (case, out[case])
    assert not (results["tmp"] / "written").exists() and not (results["tmp"] / "written2").exists()
    assert not results["marker"].exists()


def test_the_estate_secrets_are_not_readable(results):
    out = results["out"]
    for case in ("cat_secrets", "cat_secrets_tilde", "cat_link", "dash_c_secrets"):
        assert out[case]["error"] and "not-a-real-token" not in out[case]["content"], (case, out[case])


def test_reading_the_repo_still_works(results):
    out = results["out"]
    assert not out["log"]["error"] and "init" in out["log"]["content"], out["log"]
    assert not out["status"]["error"], out["status"]
    assert not out["cat_readme"]["error"] and "hello" in out["cat_readme"]["content"]
    assert not out["cat_estate_abs"]["error"] and "hello" in out["cat_estate_abs"]["content"]
    assert not out["log_dash_c"]["error"] and "init" in out["log_dash_c"]["content"], out["log_dash_c"]
