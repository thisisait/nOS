"""nos-secret says when credentials.yml overrides the derived key.

MEASURED 2026-10-18: the operator's Authentik login as pazny failed with
`nos-secret.py nos_operator` while `--tags verify` logged in — credentials.yml
set nos_operator_password, the playbook used it, the tool printed the derived
leaf. End to end on a copied layout with a fake override: --accounts marks the
row, `<key>` warns on stderr, and the override's value is never echoed."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FAKE = "not-a-real-secret-0000"
COPY = ("tools", "files/anatomy/plugins", "files/anatomy/module_utils", "files/anatomy/secrets",
        "roles", "state", "apps", "config.d", "profiles", "default.config.yml", "default.credentials.yml")


def test_an_override_is_named_and_never_printed(tmp_path):
    root = tmp_path / "repo"
    skip = shutil.ignore_patterns("__pycache__", "node_modules", "config.yml", "credentials.yml")
    for rel in COPY:
        src, dst = REPO / rel, root / rel
        shutil.copytree(src, dst, ignore=skip) if src.is_dir() else (dst.parent.mkdir(parents=True, exist_ok=True),
                                                                    shutil.copy2(src, dst))
    subprocess.run(["git", "init", "-q", str(root)], check=True)     # main checkout = root, not the real one
    (root / "credentials.yml").write_text(f'nos_operator_password: "{FAKE}"\n')
    home = tmp_path / "home"
    (home / ".nos").mkdir(parents=True)
    (home / ".nos/secrets.yml").write_text(f"nos_secret_scheme: v2\nnos_secret_master: \"{'0' * 64}\"\n")
    env = {**os.environ, "HOME": str(home)}
    run = lambda *a: subprocess.run([sys.executable, str(root / "tools/nos-secret.py"), *a],  # noqa: E731
                                    capture_output=True, text=True, env=env, cwd=root, timeout=120)

    acc = run("--accounts")
    assert acc.returncode == 0, acc.stderr
    rows = [line for line in acc.stdout.splitlines() if line.partition("→")[2].split()[:1] == ["nos_operator"]]
    assert rows and all("OVERRIDDEN in credentials.yml" in r for r in rows), acc.stdout
    assert not any("OVERRIDDEN" in r for r in acc.stdout.splitlines() if r not in rows), "only the overridden key"
    assert FAKE not in acc.stdout + acc.stderr

    key = run("nos_operator")
    assert key.returncode == 0, key.stderr
    assert "OVERRIDDEN in credentials.yml" in key.stderr and "nos_operator_password" in key.stderr
    assert key.stdout.strip() and FAKE not in key.stdout + key.stderr   # the derived leaf still goes to stdout

    clean = run("authentik_admin")
    assert "OVERRIDDEN" not in clean.stderr, "a key nobody overrode must not warn"
