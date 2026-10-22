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
    main = [*yaml.safe_load((ROLE / "tasks" / "main.yml").read_text()), *yaml.safe_load((ROLE / "tasks" / "macos.yml").read_text())]  # macos.yml: the launchd flow
    # The sign moved into pazny.medulla (row medulla-skeleton): expand its include in run order.
    medulla = REPO / "roles" / "pazny.medulla" / "tasks"
    main = [x for t in main for x in ([*yaml.safe_load((medulla / "main.yml").read_text()), *yaml.safe_load((medulla / "macos.yml").read_text())]
            if (t.get("ansible.builtin.include_role") or {}).get("name") == "pazny.medulla" else [t])]
    names = [t.get("name", "").lower() for t in main]
    at = next(i for i, t in enumerate(main) if t.get("ansible.builtin.import_tasks") == "pupil.yml")
    assert names.index("[pazny.medulla] sign the binary with it (same identity every build)") < at, \
        "the pupil is signed with the identity minted above it"
    # 2026-10-19: Linux is no longer refused; it takes linux.yml, which builds no pupil.
    top = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
    mac = next(t for t in top if t.get("ansible.builtin.import_tasks") == "macos.yml")
    assert mac["when"] == "nos_service_manager == 'launchd'", "the pupil (codesign, Tauri) stays macOS-only"
    linux = yaml.safe_load((ROLE / "tasks" / "linux.yml").read_text())
    imports = [t.get("ansible.builtin.import_tasks") or t.get("ansible.builtin.include_tasks") for t in linux]
    assert "pupil.yml" not in imports, "linux.yml must not build the pupil (no codesign, no Tauri bundle)"


def test_the_install_path_is_fixed_in_role_defaults_only():
    """The path thalamus-pupil-peer-exe enforces: one place, never a knob in the default layers.
    2026-10-14: an app the person opens from Launchpad, so the binary lives inside Iris.app."""
    d = _defaults()
    assert d["thalamus_pupil_app"] == "{{ ansible_facts['env']['HOME'] }}/Applications/Iris.app"
    assert d["thalamus_pupil_exe"] == "{{ thalamus_pupil_app }}/Contents/MacOS/nos-pupil"
    app = _render(d["thalamus_pupil_app"], ansible_facts={"env": {"HOME": "/Users/a"}})
    assert _render(d["thalamus_pupil_exe"], thalamus_pupil_app=app) == "/Users/a/Applications/Iris.app/Contents/MacOS/nos-pupil"
    sys.path.insert(0, str(REPO / "tools"))
    import nos_identity
    for var in ("thalamus_pupil_exe", "thalamus_pupil_app", "thalamus_pupil_state"):
        layered = [p.name for p in nos_identity.default_layers() if var in p.read_text()]
        assert not layered, f"{var} is declared in {layered}"
    build = _task("install the pupil binary")["ansible.builtin.shell"]
    assert re.search(r"install -m 0755 \S+/release/nos-pupil\" \{\{ thalamus_pupil_exe \| quote \}\}", build), build


def test_no_sidecar_lives_inside_the_signed_bundle():
    """A file added to a signed bundle breaks codesign --verify --strict: hashes sit beside the app."""
    d = _defaults()
    assert d["thalamus_pupil_state"] == "{{ thalamus_home }}/bin/nos-pupil"
    text = (ROLE / "tasks" / "pupil.yml").read_text()
    assert ".sha256" in text and "thalamus_pupil_exe }}.s" not in text and "thalamus_pupil_exe ~ '.s" not in text, \
        "a .sha256 next to the binary is inside Iris.app"


def test_the_bundle_names_iris_and_runs_the_pupil():
    plist = _task("info.plist")["ansible.builtin.copy"]
    body = _render(plist["content"], thalamus_pupil_identifier=_ID)
    import plistlib
    p = plistlib.loads(body.encode())
    assert (p["CFBundleExecutable"], p["CFBundleIdentifier"], p["CFBundleName"], p["CFBundlePackageType"]) == \
        ("nos-pupil", _ID, "Iris", "APPL"), p
    assert plist["dest"] == "{{ thalamus_pupil_app }}/Contents/Info.plist"
    names = [t.get("name", "").lower() for t in _pupil()]
    assert next(i for i, n in enumerate(names) if "info.plist" in n) < next(i for i, n in enumerate(names) if "sign the pupil" in n), \
        "the plist is sealed by the signature, so it is written first"


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
    assert record["ansible.builtin.copy"]["dest"] == "{{ thalamus_pupil_state }}.source-sha256"
    assert record["when"] == "_pupil_build is not skipped"
    read = _task("read the hash the pupil was built from")
    sh = read["ansible.builtin.shell"]
    assert "thalamus_pupil_state ~ '.source-sha256'" in sh, sh
    assert sh.startswith("test -x {{ thalamus_pupil_exe | quote }} &&"), "no app at the path must rebuild, whatever the hash"


def test_the_source_hash_covers_the_frontend_the_bridge_and_the_contract():
    """Run the hash script on this tree: it must answer, and see the path dep and the lock."""
    sh = _task("hash the pupil source")["ansible.builtin.shell"]
    for part in ("src", "package-lock.json", "src-tauri/src", "src-tauri/Cargo.lock",
                 "src-tauri/tauri.conf.json", "../thalamus/contract/src", "../face/src/lib/iris"):
        assert f" {part}" in sh, f"{part} can change without a rebuild"
    out = subprocess.run(["/bin/bash", "-c", _render(sh, playbook_dir=str(REPO))],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert re.fullmatch(r"[0-9a-f]{64}", out), out


def test_the_pupil_is_signed_with_the_identity_and_its_own_identifier():
    sign = _task("sign the pupil")
    sh = sign["ansible.builtin.shell"]
    assert "codesign -f -s \"$H\"" in sh and "-s -" not in sh, "ad-hoc (-s -) keeps the cdhash DR"
    assert "_thalamus_signing.stdout_lines[-1]" in sh, "a second identity, not the one thalamus uses"
    assert "-i {{ thalamus_pupil_identifier | quote }} {{ thalamus_pupil_app | quote }}" in sh, "the bundle is signed, not the bare binary"
    assert "codesign --verify --strict {{ thalamus_pupil_app | quote }}" in sh, "a changed plist re-signs though the DR matches"
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
    assert "codesign --verify --strict {{ thalamus_pupil_app | quote }}" in sh and "thalamus_pupil_identifier" in sh, sh
    rec = _task("record the installed pupil's sha256")["ansible.builtin.shell"]
    assert "shasum -a 256 {{ thalamus_pupil_exe | quote }}" in rec and ".sha256" in rec


_BORROW = re.compile(r"""(?:from|import)\s+['"](\$face|\$lib|\$iris|\.{1,2})(/[^'"]*)['"]""")
# $lib is the face's own alias (SvelteKit): the files moved into face/src/lib/iris keep it in the pupil.
_ALIAS = {"$face": REPO / "files" / "anatomy" / "face" / "src",
          "$lib": REPO / "files" / "anatomy" / "face" / "src" / "lib",
          "$iris": REPO / "files" / "anatomy" / "face" / "src" / "lib" / "iris"}


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
    assert any(h == "$iris" for _, h, _ in todo), "the pupil does not mount Iris from face/src/lib/iris"
    while todo:
        f, head, rel = todo.pop()
        hit = _resolve(_ALIAS[head], rel) if head in _ALIAS else _resolve(f.parent, head + rel)
        if hit in seen:
            continue
        seen.add(hit)
        if hit.suffix in {".ts", ".svelte", ".js", ".css"}:  # a CSS @import is a borrow too
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
    main = [*yaml.safe_load((ROLE / "tasks" / "main.yml").read_text()), *yaml.safe_load((ROLE / "tasks" / "macos.yml").read_text())]  # macos.yml: the launchd flow
    # The sign moved into pazny.medulla (row medulla-skeleton): expand its include in run order.
    medulla = REPO / "roles" / "pazny.medulla" / "tasks"
    main = [x for t in main for x in ([*yaml.safe_load((medulla / "main.yml").read_text()), *yaml.safe_load((medulla / "macos.yml").read_text())]
            if (t.get("ansible.builtin.include_role") or {}).get("name") == "pazny.medulla" else [t])]
    at = next(i for i, t in enumerate(main) if t.get("ansible.builtin.import_tasks") == "pupil.yml")
    for needle in ("render launchd plist", "bootstrap launchd job", "flush handlers"):
        before = next(i for i, t in enumerate(main) if needle in t.get("name", "").lower())
        assert before < at, f"the pupil is imported before '{needle}'"


_LEAF = "ab" * 20  # a leaf-shaped placeholder, not credential-shaped
_ID = "eu.thisisait.nos.pupil"


def _run_verify(tmp: pathlib.Path, *, recorded: str | None = None, verify_rc: int = 0,
                ident: str = _ID, leaf: str = _LEAF, keychain: str = _LEAF.upper()) -> subprocess.CompletedProcess:
    """The verify script on a fake binary, codesign and security stubbed: what the file and its DR say."""
    app = tmp / "Iris.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    exe = app / "Contents" / "MacOS" / "nos-pupil"
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
    sh = _render(_task("verify")["ansible.builtin.shell"], thalamus_pupil_exe=str(exe), thalamus_pupil_app=str(app),
                 thalamus_pupil_state=str(tmp / "nos-pupil"), thalamus_pupil_identifier=_ID,
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


def test_the_icon_is_committed_not_converted_at_converge():
    """Live 2026-10-14: sips failed under ansible (Error 13 writing its temp file), so the build
    failed after cargo had finished. The icns is built once and committed; converge only copies it."""
    sh = _task("install the pupil binary")["ansible.builtin.shell"]
    assert "sips" not in sh and "iconutil" not in sh, sh
    assert "src-tauri/icons/Iris.icns" in sh, sh
    icns = PUPIL / "src-tauri" / "icons" / "Iris.icns"
    assert icns.read_bytes()[:4] == b"icns", "not an icns file"
