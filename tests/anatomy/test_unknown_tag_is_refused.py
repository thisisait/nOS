"""nos refuses a --tags name no task carries (exit 64, with the near spelling).

11-02 `nos --tags device_gateway,wing` (the tag is device-gateway) converged
failed=0 and deployed nothing. Runs the real tools/nos against a PATH-stubbed
ansible-playbook whose --list-tags output is fixed; the list is cached per HEAD."""
import os, stat as statmod, subprocess
from pathlib import Path

NOS = str(Path(__file__).resolve().parents[2] / "tools/nos")
LIST = ("playbook: main.yml\n\n  play #1 (all): nOS\tTAGS: []\n"
        "      TASK TAGS: [always, device-gateway, mcp_gateway, wing]\n")


def _env(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.yml").write_text("---\n")
    for c in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t",
                                            "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(src), *c], check=True)
    stub = tmp_path / "bin" / "ansible-playbook"
    stub.parent.mkdir()
    stub.write_text('#!/bin/sh\ncase "$*" in *--list-tags*) echo x >> "$HOME/lt.calls"; '
                    f"printf '{LIST}' ;; *) echo RAN ;; esac\n")
    stub.chmod(stub.stat().st_mode | statmod.S_IEXEC)
    home = tmp_path / "home"
    home.mkdir()
    return dict(os.environ, PATH=f"{stub.parent}:{os.environ['PATH']}", HOME=str(home),
                NOS_SRC=str(src))


def _nos(env, *args):
    return subprocess.run([NOS, *args], env=env, capture_output=True, text=True, timeout=30)


def test_an_unknown_tag_is_refused_with_the_near_spelling(tmp_path):
    env = _env(tmp_path)
    r = _nos(env, "--tags", "device_gateway,wing")
    assert r.returncode == 64 and "RAN" not in r.stdout, (r.returncode, r.stdout, r.stderr)
    assert "did you mean device-gateway" in r.stderr, r.stderr
    r = _nos(env, "--skip-tags=nosuch")
    assert r.returncode == 64 and "nosuch" in r.stderr, r.stderr


def test_a_declared_tag_passes_and_the_list_is_cached(tmp_path):
    env = _env(tmp_path)
    for args in (["--tags", "device-gateway,wing"], ["-t", "mcp_gateway"], ["--tags=always"]):
        r = _nos(env, *args)
        assert r.returncode == 0 and "RAN" in r.stdout, (args, r.stderr)
    calls = (Path(env["HOME"]) / "lt.calls").read_text().count("x")
    assert calls == 1, f"--list-tags ran {calls}x for one clean HEAD"
