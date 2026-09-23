"""The face shell must admit a body as large as Bone will store.

MEASURED 2026-09-23 on the live estate: a 100 KB upload through /bff/vfs
answered 200, a 2 MB one answered 500. adapter-node's default incoming-body cap
is 512 KB, and over the cap it does not refuse politely — it ERRORS the request
stream the BFF is mid-way through piping to Bone, so undici raises
`TypeError: fetch failed` and the browser is handed a bare "Internal Error".
Every phone photo is 2-5 MB, which means the camera button in the Files app had
never once stored a document; the operator saw the camera open and nothing
arrive, with no error naming a size.

Two components own a ceiling here and they must not disagree: Bone's
`_MAX_UPLOAD_BYTES` (what will be written) and the shell's `BODY_SIZE_LIMIT`
(what may be received). A shell cap BELOW Bone's is the bug above; the gate
therefore reads both numbers out of their real artifacts rather than trusting
the comment that says they match.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "roles/pazny.face/templates/compose.yml.j2"
DEFAULTS = ROOT / "roles/pazny.face/defaults/main.yml"
BONE_VFS = ROOT / "files/anatomy/bone/vfs.py"


def _bone_cap() -> int:
    m = re.search(r"^_MAX_UPLOAD_BYTES\s*=\s*([0-9 *]+)", BONE_VFS.read_text(), re.M)
    assert m, "bone/vfs.py no longer declares _MAX_UPLOAD_BYTES"
    return eval(m.group(1).strip(), {"__builtins__": {}})  # noqa: S307 — digits and * only


def _face_cap() -> int:
    """The number the container actually gets: the template's default filter."""
    env = COMPOSE.read_text()
    m = re.search(r'BODY_SIZE_LIMIT:\s*"\{\{\s*(\w+)\s*\|\s*default\((\d+)\)\s*\}\}"', env)
    assert m, "the face compose template does not set BODY_SIZE_LIMIT from a defaulted var"
    var, inline_default = m.group(1), int(m.group(2))
    d = re.search(rf"^{var}:\s*(\d+)", DEFAULTS.read_text(), re.M)
    assert d, f"{var} is used in the template but not declared in defaults/main.yml"
    declared = int(d.group(1))
    assert declared == inline_default, (
        f"{var} is {declared} in defaults but the template falls back to {inline_default} — "
        "two spellings of one ceiling drift apart silently"
    )
    return declared


def test_the_shell_admits_what_bone_will_store():
    bone, face = _bone_cap(), _face_cap()
    assert face >= bone, (
        f"the shell caps an incoming body at {face} B but Bone stores up to {bone} B — "
        "adapter-node kills the stream mid-pipe and the browser gets a bare 500"
    )


def test_the_cap_is_large_enough_for_a_photograph():
    """The concrete failure this was found by: a camera shot is megabytes."""
    assert _face_cap() >= 8 * 1024 * 1024, (
        "a phone photograph is 2-5 MB; a cap under that makes the camera button "
        "in the Files app decorative"
    )
