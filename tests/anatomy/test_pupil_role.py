"""The pupil on the host: pazny.thalamus builds it, installs it at one fixed path, signs it.

Roadmap row pupil-build-role. Today the pupil runs from `npm run dev` in the repo, so there is no
path a peer check could name. thalamus_pupil_exe is that path; row thalamus-pupil-peer-exe
enforces it in serve. Offline: the tasks are parsed, the source hash script is run on this tree.
"""
from __future__ import annotations

import json
import pathlib
import re
import shlex
import subprocess
import sys

import jinja2
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ROLE = REPO / "roles" / "pazny.thalamus"
PUPIL = REPO / "files" / "anatomy" / "pupil"


def _pupil() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / "pupil.yml").read_text())


def _task(needle: str) -> dict:
    return next(t for t in _pupil() if needle in t.get("name", "").lower())


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())


def _render(text: str, **ctx) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["quote"] = shlex.quote
    return env.from_string(text).render(**ctx)


def test_the_role_reaches_the_pupil_statically_after_the_thalamus_is_signed():
    """import_tasks, not include_tasks: --tags thalamus reaches a static import, not a dynamic one."""
    main = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    names = [t.get("name", "").lower() for t in main]
    at = next(i for i, t in enumerate(main) if t.get("ansible.builtin.import_tasks") == "pupil.yml")
    assert names.index("[pazny.thalamus] sign the binary with it (same identity every build)") < at, \
        "the pupil is signed with the identity minted above it"
    assert main[0]["ansible.builtin.fail"] and "launchd" in str(main[0]["when"]), \
        "Linux is refused before the pupil (no systemd unit, no codesign): the stated skip"


def test_the_install_path_is_fixed_in_role_defaults_only():
    """The path thalamus-pupil-peer-exe enforces: one place, never a knob in the default layers."""
    d = _defaults()
    assert d["thalamus_pupil_exe"] == "{{ thalamus_home }}/bin/nos-pupil"
    assert _render(d["thalamus_pupil_exe"], thalamus_home="/h/thalamus") == "/h/thalamus/bin/nos-pupil"
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    layered = [p.name for p in nos_identity.default_layers() if "thalamus_pupil_exe" in p.read_text()]
    assert not layered, f"thalamus_pupil_exe is declared in {layered}"
    build = _task("install the pupil binary")["ansible.builtin.shell"]
    assert re.search(r"install -m 0755 \S+/release/nos-pupil\" \{\{ thalamus_pupil_exe \| quote \}\}", build), build


def test_the_build_ignores_npm_scripts_and_builds_the_locked_release():
    sh = _task("install the pupil binary")["ansible.builtin.shell"]
    assert "npm ci --ignore-scripts" in sh, "a dependency's install script runs on the host"
    assert "--release" in sh and "--locked" in sh and "CARGO_TARGET_DIR" in sh, sh
    # Without custom-protocol tauri builds cfg(dev): no embedded frontend, a dev binary.
    assert "--features tauri/custom-protocol" in sh, sh
    assert sh.index("npm ci") < sh.index("npm run build") < sh.index("build --release"), \
        "cargo embeds ../dist, so the frontend is built first"


def test_the_build_is_skipped_when_the_source_is_unchanged():
    build = _task("install the pupil binary")
    assert build["when"] == "_pupil_src_sha.stdout != (_pupil_built_sha.stdout | default(''))", build["when"]
    record = _task("record the hash the pupil was built from")
    assert record["ansible.builtin.copy"]["dest"] == "{{ thalamus_pupil_exe }}.source-sha256"
    assert record["when"] == "_pupil_build is not skipped"
    read = _task("read the hash the pupil was built from")
    assert "{{ thalamus_pupil_exe }}.source-sha256" in read["ansible.builtin.command"]


def test_the_source_hash_covers_the_frontend_the_bridge_and_the_contract():
    """Run the hash script on this tree: it must answer, and see the path dep and the lock."""
    sh = _task("hash the pupil source")["ansible.builtin.shell"]
    for part in ("src", "package-lock.json", "src-tauri/src", "src-tauri/Cargo.lock",
                 "src-tauri/tauri.conf.json", "../thalamus/contract/src"):
        assert f" {part}" in sh, f"{part} can change without a rebuild"
    out = subprocess.run(["/bin/bash", "-c", _render(sh, playbook_dir=str(REPO))],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{64}", out), out


def test_the_pupil_is_signed_with_the_identity_and_its_own_identifier():
    sign = _task("sign the pupil")
    sh = sign["ansible.builtin.shell"]
    assert "codesign -f -s \"$H\"" in sh and "-s -" not in sh, "ad-hoc (-s -) keeps the cdhash DR"
    assert "_thalamus_signing.stdout_lines[-1]" in sh, "a second identity, not the one thalamus uses"
    assert "-i {{ thalamus_pupil_identifier | quote }}" in sh
    conf = json.loads((PUPIL / "src-tauri" / "tauri.conf.json").read_text())
    assert _defaults()["thalamus_pupil_identifier"] == conf["identifier"] == "eu.thisisait.nos.pupil"
    assert _defaults()["thalamus_pupil_identifier"] != _defaults()["thalamus_launchd_label"]
    assert "_thalamus_signing" in sign["when"], "--check mints nothing, so there is nothing to sign with"


def test_build_then_sign_then_record_then_verify():
    names = [t.get("name", "").lower() for t in _pupil()]
    order = ["install the pupil binary", "sign the pupil", "record the installed pupil's sha256", "verify"]
    at = [next(i for i, n in enumerate(names) if o in n) for o in order]
    assert at == sorted(at), dict(zip(order, at))


def test_verify_reads_the_installed_binary():
    """The effect: the hash of the file at the fixed path, and the signature on it — not the build's word."""
    v = _task("verify")
    assert "verify" in v["tags"] and v["changed_when"] is False
    sh = v["ansible.builtin.shell"]
    assert "shasum -a 256 {{ thalamus_pupil_exe | quote }}" in sh, sh
    assert "codesign --verify" in sh and "thalamus_pupil_identifier" in sh, sh
    rec = _task("record the installed pupil's sha256")["ansible.builtin.shell"]
    assert "shasum -a 256 {{ thalamus_pupil_exe | quote }}" in rec and ".sha256" in rec


_BORROW = re.compile(r"""(?:from|import)\s+['"](\$face|\$ui|\.{1,2})(/[^'"]*)['"]""")
_ALIAS = {"$face": REPO / "files" / "anatomy" / "face" / "src",
          "$ui": REPO / "files" / "anatomy" / "face" / "src" / "lib" / "components" / "ui"}


def _resolve(base: pathlib.Path, rel: str) -> pathlib.Path:
    p = (base / rel.lstrip("/")).resolve()
    hit = next((c for c in (p, *(p.with_name(p.name + e) for e in (".ts", ".svelte", ".js"))) if c.is_file()), None)
    assert hit, f"{rel} from {base} resolves to no file"
    return hit


def test_the_source_hash_covers_what_vite_borrows_from_the_face():
    """vite.config.ts aliases ../face/src: every face file the pupil imports, and theirs, rebuilds it."""
    vite = (PUPIL / "vite.config.ts").read_text()
    aliases = set(re.findall(r"(\$\w+):", vite.split("alias:", 1)[1].split("}", 1)[0]))
    assert aliases == set(_ALIAS), f"vite aliases {aliases}: teach this gate the new one"
    seen: set[pathlib.Path] = set()
    todo = [(f, m.group(1), m.group(2)) for f in PUPIL.joinpath("src").rglob("*")
            if f.suffix in {".ts", ".svelte"} and not f.name.endswith(".test.ts")
            for m in _BORROW.finditer(f.read_text()) if m.group(1) in _ALIAS]
    assert todo, "the pupil borrows nothing from the face: drop ../face from this gate"
    while todo:
        f, head, rel = todo.pop()
        hit = _resolve(_ALIAS[head], rel) if head in _ALIAS else _resolve(f.parent, head + rel)
        if hit in seen:
            continue
        seen.add(hit)
        if hit.suffix in {".ts", ".svelte", ".js"}:
            todo += [(hit, m.group(1), m.group(2)) for m in _BORROW.finditer(hit.read_text())]
    sh = _task("hash the pupil source")["ansible.builtin.shell"]
    tail = "| xargs cat | shasum -a 256 | cut -d' ' -f1"
    assert tail in sh, sh
    listed = subprocess.run(["/bin/bash", "-c", _render(sh.replace(tail, ""), playbook_dir=str(REPO))],
                            capture_output=True, text=True, check=True, cwd=PUPIL).stdout.split()
    hashed = {(PUPIL / p).resolve() for p in listed}
    missed = sorted(str(p.relative_to(REPO)) for p in seen if p.is_relative_to(_ALIAS["$face"]) and p not in hashed)
    assert not missed, f"a change to these rebuilds no pupil: {missed}"


def test_the_pupil_comes_after_the_thalamus_is_serving():
    """A failed pupil build (npm, tauri) must not hold back the daemon's plist and bootstrap."""
    main = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    at = next(i for i, t in enumerate(main) if t.get("ansible.builtin.import_tasks") == "pupil.yml")
    for needle in ("render launchd plist", "bootstrap launchd job", "flush handlers"):
        before = next(i for i, t in enumerate(main) if needle in t.get("name", "").lower())
        assert before < at, f"the pupil is imported before '{needle}'"


_LEAF = "0123456789abcdef0123456789abcdef01234567"
_ID = "eu.thisisait.nos.pupil"


def _run_verify(tmp: pathlib.Path, *, recorded: str | None = None, verify_rc: int = 0,
                ident: str = _ID, leaf: str = _LEAF, keychain: str = _LEAF.upper()) -> subprocess.CompletedProcess:
    """The verify script on a fake binary, codesign and security stubbed: what the file and its DR say."""
    exe = tmp / "nos-pupil"
    exe.write_bytes(b"pupil")
    now = subprocess.run(["shasum", "-a", "256", str(exe)], capture_output=True, text=True, check=True).stdout.split()[0]
    (tmp / "nos-pupil.sha256").write_text(now if recorded is None else recorded)
    bin_ = tmp / "stub"
    bin_.mkdir()
    (bin_ / "codesign").write_text(
        "#!/bin/bash\ncase \"$1\" in --verify) exit %d ;; -d) "
        "echo 'designated => identifier \"%s\" and certificate leaf = H\"%s\"' >&2 ;; *) exit 9 ;; esac\n"
        % (verify_rc, ident, leaf))
    (bin_ / "security").write_text("#!/bin/bash\necho 'SHA-1 hash: %s'\n" % keychain)
    for s in bin_.iterdir():
        s.chmod(0o755)
    sh = _render(_task("verify")["ansible.builtin.shell"], thalamus_pupil_exe=str(exe), thalamus_pupil_identifier=_ID,
                 thalamus_signing_cn="nOS local code signing", thalamus_signing_keychain=str(tmp / "login.keychain-db"))
    import os
    return subprocess.run(["/bin/bash", "-c", sh], capture_output=True, text=True,
                          env={**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"})


def test_verify_passes_the_recorded_binary_signed_by_the_identity(tmp_path):
    r = _run_verify(tmp_path)
    assert r.returncode == 0, r.stderr
    assert re.fullmatch(r"[0-9a-f]{64}", r.stdout.strip()), r.stdout


def test_verify_fails_a_binary_that_is_not_the_recorded_one(tmp_path):
    r = _run_verify(tmp_path, recorded="0" * 64)
    assert r.returncode != 0 and "recorded" in r.stderr, (r.stdout, r.stderr)


def test_verify_fails_a_signature_that_does_not_verify(tmp_path):
    assert _run_verify(tmp_path, verify_rc=1).returncode != 0


def test_verify_fails_another_identifier(tmp_path):
    r = _run_verify(tmp_path, ident="eu.thisisait.nos.thalamus")
    assert r.returncode != 0, (r.stdout, r.stderr)


def test_verify_fails_a_leaf_that_is_not_the_keychain_identity(tmp_path):
    """Any valid signature verifies; only the leaf says it is the identity the TCC grant binds to."""
    r = _run_verify(tmp_path, leaf="f" * 40)
    assert r.returncode != 0, (r.stdout, r.stderr)
    (tmp_path / "none").mkdir()
    r = _run_verify(tmp_path / "none", keychain="")
    assert r.returncode != 0, "no identity in the keychain is no leaf to match, not a pass"
