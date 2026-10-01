"""Gate: the loader's docker_exec splits a cmd like a shell.

2026-10-01: `cmd.split()` kept the quotes of --clientsecret="…", so Nextcloud
stored the OIDC secret WITH them; every SSO login failed with "Client
authentication failed" after a tagged run. A full run masked it by resetting
the secret through a shell later.
"""
import subprocess

from module_utils import load_plugins


def test_quotes_are_shell_quotes(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(load_plugins.subprocess, "run", fake_run)
    step = {"container": "nextcloud", "compose_project": "iiab",
            "cmd": 'php occ x --clientsecret="{{ s }}" --execute="echo a b"'}
    load_plugins._docker_exec(step, {}, {"s": "abc", "stacks_dir": "/tmp"})
    assert seen["argv"][-3:] == ["x", "--clientsecret=abc", "--execute=echo a b"]
