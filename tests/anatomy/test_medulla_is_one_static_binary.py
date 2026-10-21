"""The medulla is one binary that links no host runtime, and `medulla thalamus` is today's thalamus.

WHY. ssot/doctrine/medulla.md §1: one static Rust binary runs the host organs, and its
subcommands replace wing/bin/*.php. A binary that links libphp/libpython/libnode would
bring back the host runtime it replaces. Roadmap row medulla-skeleton: during coexistence
the plist still runs `thalamus`, a symlink to the medulla, so argv[0] picks the thalamus CLI.
"""
from __future__ import annotations

import functools
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ROOT = REPO / "files/anatomy/thalamus"
HOST_RUNTIMES = re.compile(r"lib(php|python|node|ruby)", re.I)
# Linux: glibc's own pieces only; macOS: anything outside the OS image is not a system lib.
LINUX_SYSTEM = {"linux-vdso.so.1", "libc.so.6", "libm.so.6", "libgcc_s.so.1", "libpthread.so.0",
                "libdl.so.2", "librt.so.1", "libresolv.so.2"}

pytestmark = pytest.mark.skipif(not shutil.which("cargo"), reason="cargo builds the medulla")


@functools.cache
def _meta() -> dict:
    r = subprocess.run(["cargo", "metadata", "--format-version", "1", "--no-deps",
                        "--manifest-path", str(ROOT / "Cargo.toml")], capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"no workspace root Cargo.toml in files/anatomy/thalamus\n{r.stderr[-800:]}"
    return json.loads(r.stdout)


@functools.cache
def _bins() -> pathlib.Path:
    meta = _meta()
    assert any(t["name"] == "medulla" and "bin" in t["kind"] for p in meta["packages"] for t in p["targets"]), \
        "the workspace has no `medulla` bin target"
    r = subprocess.run(["cargo", "build", "--locked", "-p", "medulla", "-p", "thalamus"], cwd=ROOT,
                       capture_output=True, text=True, timeout=1800, check=False)
    assert r.returncode == 0, r.stderr[-4000:]
    return pathlib.Path(meta["target_directory"]) / "debug"


def _run(exe, *args):
    env = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", "NOS_REPO_ROOT": "/nonexistent",
           "KEAP_PROXY_SHARED_SECRET": "x"}  # past serve's env checks, so the usage line is what answers
    return subprocess.run([str(exe), *args], capture_output=True, text=True, env=env, timeout=30, check=False)


def _foreign(libs: list[str], darwin: bool) -> list[str]:
    """The linked libraries that are a host runtime or not on the system allow-list."""
    if darwin:
        return [lib for lib in libs if HOST_RUNTIMES.search(lib) or not lib.startswith(("/usr/lib/", "/System/Library/"))]
    return [lib for lib in libs if HOST_RUNTIMES.search(lib)
            or (pathlib.Path(lib).name not in LINUX_SYSTEM and "ld-linux" not in lib)]


def test_the_link_check_takes_only_named_system_libraries():
    """/usr/lib and /System/Library hold more than libc: libxml2, Python.framework, libcurl."""
    real = ["/usr/lib/libiconv.2.dylib", "/usr/lib/libSystem.B.dylib"]  # the medulla, otool -L 2026-10-21
    assert _foreign(real, darwin=True) == []
    for lib in ("/usr/lib/libxml2.2.dylib", "/usr/lib/libcurl.4.dylib", "/opt/homebrew/lib/libphp.dylib",
                "/System/Library/Frameworks/Python.framework/Versions/2.7/Python"):
        assert _foreign([*real, lib], darwin=True) == [lib], f"{lib} passes as a system library"
    glibc = ["linux-vdso.so.1", "/lib/x86_64-linux-gnu/libc.so.6", "/lib64/ld-linux-x86-64.so.2"]
    assert _foreign(glibc, darwin=False) == []
    for lib in ("/lib/x86_64-linux-gnu/libpython3.12.so.1.0", "/lib/x86_64-linux-gnu/libssl.so.3"):
        assert _foreign([*glibc, lib], darwin=False) == [lib], f"{lib} passes as a system library"


def test_the_medulla_links_no_host_runtime():
    exe = _bins() / "medulla"
    if sys.platform == "darwin":
        out = subprocess.run(["otool", "-L", str(exe)], capture_output=True, text=True, check=True).stdout
        libs = [ln.split()[0] for ln in out.splitlines()[1:] if ln.strip()]
    else:
        out = subprocess.run(["ldd", str(exe)], capture_output=True, text=True, check=False).stdout
        libs = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
    assert libs, out
    assert not _foreign(libs, sys.platform == "darwin"), f"host runtime or non-system libraries: {_foreign(libs, sys.platform == 'darwin')}\n{out}"


def test_medulla_thalamus_serve_is_todays_thalamus():
    d = _bins()
    today = _run(d / "thalamus", "serve")
    via = _run(d / "medulla", "thalamus", "serve")
    assert today.returncode == 1 and "usage: thalamus serve --data-dir <dir>" in today.stderr, today.stderr
    assert (via.returncode, via.stderr) == (today.returncode, today.stderr)
    version = next(p["version"] for p in _meta()["packages"] if p["name"] == "medulla")
    v = _run(d / "medulla", "--version")
    assert v.returncode == 0 and v.stdout.strip() == f"medulla {version}", v


def test_a_thalamus_symlink_runs_the_thalamus_cli(tmp_path):
    d = _bins()
    for name in ("thalamus", "iris"):
        link = tmp_path / name
        link.symlink_to(d / "medulla")
        r = _run(link, "serve")
        assert r.returncode == 1 and "usage: thalamus serve --data-dir <dir>" in r.stderr, (name, r.stderr)
