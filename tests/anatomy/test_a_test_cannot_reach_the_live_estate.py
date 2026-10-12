"""Gate: an anatomy test cannot reach the live estate without opting in.

MEASURED 2026-10-02 on the dev box, before tests/anatomy/_live_guard.py:
`Path.home()/.nos/secrets.yml` readable, `docker inspect iiab-rustfs-1` rc 0
with the bucket keys in its output, `connect(127.0.0.1:9000)` answered by the
live Wing. That is the path the 2026-09-20 RustFS incident took (7 objects,
Object-Lock COMPLIANCE, 3650 days) — and an anatomy gate walked part of
it until 2026-10-02: test_table_anchors_resolve POSTed /agent/v1/lint/run to the live KEAP
with the RW token. Every assertion below is RED on that state and green only
because the boundary holds for the test and for the children it spawns.
"""

from __future__ import annotations

import os
import pathlib
import re
import socket
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request

import pytest

import _live_guard as guard

pytestmark = pytest.mark.skipif(
    guard.live_run(), reason=f"{guard.ENV}=1 — the operator disarmed the boundary for this run")


def test_the_secret_store_is_invisible_in_process_and_to_children():
    assert str(pathlib.Path.home()) == os.environ["HOME"] != guard._real["HOME"]
    assert not (pathlib.Path.home() / ".nos" / "secrets.yml").exists()
    child = subprocess.run(["sh", "-c", 'test -e "$HOME/.nos/secrets.yml"'])
    assert child.returncode != 0, "a child process can still read ~/.nos/secrets.yml"
    # the rest of HOME still resolves — ~/.ansible, ~/.gitconfig, ~/.cache are symlinked through
    real = pathlib.Path(guard._real["HOME"])
    assert {p.name for p in real.iterdir()} | {".nos"} <= {p.name for p in pathlib.Path.home().iterdir()}
    for holder in guard.HIDDEN:                     # the unit files carry the organs' tokens
        fake = pathlib.Path.home() / holder
        assert not fake.is_symlink() and (not fake.exists() or not any(fake.iterdir())), holder


def test_docker_is_refused_for_children():
    r = subprocess.run(["docker", "inspect", "iiab-rustfs-1"], capture_output=True, text=True)
    assert r.returncode == 125 and "offline" in r.stderr, (r.returncode, r.stderr[:200])


def test_a_loopback_service_port_is_refused_before_the_packet():
    with pytest.raises(ConnectionRefusedError, match="tests/anatomy is offline"):
        socket.create_connection(("127.0.0.1", 9000), timeout=1)
    with pytest.raises(urllib.error.URLError, match="offline"):       # urllib/requests use the same door
        urllib.request.urlopen("http://127.0.0.1:8091/agent/v1/lint", timeout=1)


def test_an_ephemeral_port_still_serves_the_tests_own_server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        socket.create_connection(srv.getsockname(), timeout=1).close()
    finally:
        srv.close()


def test_secret_shaped_env_is_scrubbed():
    assert not [k for k in os.environ if guard.SECRET_ENV.search(k)]


def test_lifted_opens_the_boundary_for_one_block():
    """`lifted()` is the door a live test gets once NOS_LIVE=1 has let it run."""
    assert os.environ["HOME"] != guard._real["HOME"]
    with guard.lifted():
        assert os.environ["HOME"] == guard._real["HOME"]
        assert socket.socket.connect is guard._real["connect"]
        assert os.environ["PATH"] == guard._real["PATH"], "the docker shim is still on PATH"
    assert os.environ["HOME"] != guard._real["HOME"]
    assert socket.socket.connect is not guard._real["connect"]


def test_a_live_mark_is_skipped_without_nos_live(tmp_path):
    """A planted `@pytest.mark.live` test does not run unless NOS_LIVE=1.

    MEASURED 2026-10-12: the mark lifted the boundary, so the test body ran
    inside a plain `pytest tests/anatomy` and the verdict depended on whatever
    the estate answered. The planted body only raises — it is not a live probe.
    """
    planted = tmp_path / "test_planted_live.py"
    planted.write_text(textwrap.dedent("""\
        import pytest

        @pytest.mark.live
        def test_planted_live():
            raise AssertionError("ran without NOS_LIVE")
    """))
    anatomy = pathlib.Path(__file__).resolve().parent
    (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""\
        import importlib.util
        import sys
        sys.path.insert(0, {str(anatomy)!r})
        spec = importlib.util.spec_from_file_location(
            "anatomy_conftest", {str(anatomy / "conftest.py")!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pytest_configure = mod.pytest_configure
        _offline_boundary = mod._offline_boundary
    """))
    env = {k: v for k, v in os.environ.items() if k != guard.ENV}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-1500:]
    assert re.search(r"SKIPPED.*NOS_LIVE", out), out[-1500:]
    assert "ran without NOS_LIVE" not in out, out[-1500:]


def _real_docker_binary(path: str) -> str | None:
    """An executable named docker that is not this suite's PATH shim."""
    for entry in path.split(os.pathsep):
        if "nos-pytest-bin-" in entry or "nos-pytest-docker-cli-" in entry:
            continue
        cand = pathlib.Path(entry) / "docker"
        if not cand.is_file() or not os.access(cand, os.X_OK):
            continue
        try:
            head = cand.read_bytes()[:800]
        except OSError:
            continue
        if b"refused by tests/anatomy/_live_guard.py" in head:
            continue
        return str(cand)
    return None


def test_docker_cli_mark_allows_only_compose_config(tmp_path):
    """`@pytest.mark.docker_cli` execs the real CLI for `compose config` only.

    The orphan-compose gate carried `@pytest.mark.live` only to step past the
    docker shim, so a default run skipped it. This planted run is the pin:
    compose config over a temp file may reach the real binary; every other
    docker invocation still exits 125; HOME, secrets and loopback stay shut.
    """
    planted = tmp_path / "test_planted_docker_cli.py"
    planted.write_text(textwrap.dedent("""\
        import os
        import pathlib
        import socket
        import subprocess

        import pytest

        def _real_docker():
            for entry in os.environ.get("PATH", "").split(os.pathsep):
                if "nos-pytest-bin-" in entry or "nos-pytest-docker-cli-" in entry:
                    continue
                cand = pathlib.Path(entry) / "docker"
                if not cand.is_file() or not os.access(cand, os.X_OK):
                    continue
                try:
                    head = cand.read_bytes()[:800]
                except OSError:
                    continue
                if b"refused by tests/anatomy/_live_guard.py" in head:
                    continue
                return cand
            return None

        def _compose(tmp_path):
            compose = tmp_path / "compose.yml"
            compose.write_text("services:\\n  web:\\n    image: nginx:alpine\\n")
            return compose

        @pytest.mark.docker_cli
        def test_compose_config_reaches_the_real_docker(tmp_path):
            if _real_docker() is None:
                pytest.skip("docker CLI not on PATH")
            compose = _compose(tmp_path)
            shown = subprocess.run(
                ["docker", "compose", "-f", str(compose), "config"],
                capture_output=True, text=True,
            )
            assert shown.returncode == 0, (shown.returncode, shown.stderr[-400:])
            assert "nginx:alpine" in shown.stdout
            assert "offline" not in shown.stderr
            quiet = subprocess.run(
                ["docker", "compose", "-f", str(compose), "config", "-q"],
                capture_output=True, text=True,
            )
            assert quiet.returncode == 0, (quiet.returncode, quiet.stderr[-400:])

        @pytest.mark.docker_cli
        @pytest.mark.parametrize("args", [
            ("ps",),
            ("inspect", "x"),
            ("compose", "up"),
            ("compose", "-f", "f.yml", "ps"),
            ("--context", "x", "compose", "config"),
            ("-H", "tcp://127.0.0.1:2375", "compose", "config"),
            ("--host", "tcp://127.0.0.1:2375", "compose", "config"),
        ])
        def test_other_docker_is_still_refused(args):
            r = subprocess.run(["docker", *args], capture_output=True, text=True)
            assert r.returncode == 125, (args, r.returncode, r.stderr[-300:])
            assert "offline" in r.stderr

        @pytest.mark.docker_cli
        def test_docker_host_env_is_still_refused(tmp_path):
            compose = _compose(tmp_path)
            env = os.environ.copy()
            env["DOCKER_HOST"] = "unix:///tmp/nos-dead-docker.sock"
            r = subprocess.run(
                ["docker", "compose", "-f", str(compose), "config"],
                capture_output=True, text=True, env=env,
            )
            assert r.returncode == 125, (r.returncode, r.stderr[-300:])
            assert "offline" in r.stderr

        @pytest.mark.docker_cli
        def test_only_the_docker_door_moves():
            import _live_guard as guard
            assert os.environ["HOME"] != guard._real["HOME"]
            assert os.environ["PATH"] != guard._real["PATH"]
            assert not (pathlib.Path.home() / ".nos" / "secrets.yml").exists()
            assert not [k for k in os.environ if guard.SECRET_ENV.search(k)]
            with pytest.raises(ConnectionRefusedError, match="offline"):
                socket.create_connection(("127.0.0.1", 9000), timeout=1)

        def test_compose_config_without_the_mark_is_refused(tmp_path):
            compose = _compose(tmp_path)
            r = subprocess.run(
                ["docker", "compose", "-f", str(compose), "config"],
                capture_output=True, text=True,
            )
            assert r.returncode == 125, (r.returncode, r.stderr[-300:])
            assert "offline" in r.stderr
    """))
    anatomy = pathlib.Path(__file__).resolve().parent
    (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""\
        import importlib.util
        import sys
        sys.path.insert(0, {str(anatomy)!r})
        spec = importlib.util.spec_from_file_location(
            "anatomy_conftest", {str(anatomy / "conftest.py")!r})
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pytest_configure = mod.pytest_configure
        _offline_boundary = mod._offline_boundary
    """))
    env = {k: v for k, v in os.environ.items() if k != guard.ENV}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-rs", "--tb=line",
         "-p", "no:cacheprovider", str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    out = r.stdout + r.stderr
    has_cli = _real_docker_binary(guard._real["PATH"]) is not None
    assert r.returncode == 0, out[-4000:]
    if has_cli:
        assert "test_compose_config_reaches_the_real_docker PASSED" in out, out[-2500:]
    else:
        assert re.search(r"docker CLI not on PATH", out), out[-2500:]
        assert "test_compose_config_reaches_the_real_docker PASSED" not in out
    assert "test_compose_config_without_the_mark_is_refused PASSED" in out, out[-2500:]
    assert "FAILED" not in out
