"""The committed Bone OpenAPI must be what the routes actually declare.

MEASURED 2026-08-29. `files/anatomy/skills/contracts/bone.openapi.yml` was
nineteen days stale: `session_uuid` had been added to the propose payload — the
field the whole proposal-lineage join depends on — and the artifact an agent
reads to learn Bone's shape did not have it. CI's "Contracts drift check" job
found it, correctly, and one push later.

WHY A SECOND CHECKER IS NOT A SECOND TRUTH. It regenerates with the same script
CI runs (`bin/export-openapi.py`) and compares to the same committed file; it
cannot disagree with CI about the answer, only about WHEN. That is the point.
The estate keeps relearning one lesson — the duty belongs in the lane that
causes the change — most recently on the face layout pin, where a regen in the
pytest lane reddened the face lane an hour later. Editing a Bone route is a
Python change made in the pytest lane; this is where the bill should arrive.

Only Bone is covered here. The two Wing artifacts need `php`, which is a
declared tool dependency rather than something every pytest environment has,
and CI still checks all three. A partial local mirror that says so is honest;
one that implied it covered everything would not be.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
EXPORT = REPO / "files/anatomy/bone/bin/export-openapi.py"
COMMITTED = REPO / "files/anatomy/skills/contracts/bone.openapi.yml"


def _regenerate() -> str | None:
    """Returns the freshly exported YAML, or None when the exporter cannot run
    here (FastAPI absent). None is a skip, never a pass."""
    out = pathlib.Path(tempfile.mkdtemp(prefix="bonecontract")) / "bone.openapi.yml"
    try:
        done = subprocess.run([sys.executable, str(EXPORT), "--output", str(out)],
                              capture_output=True, text=True, timeout=120, cwd=REPO)
    except Exception:  # noqa: BLE001
        return None
    try:
        if done.returncode != 0 or not out.is_file():
            return None
        return out.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def test_the_committed_openapi_matches_the_routes() -> None:
    fresh = _regenerate()
    if fresh is None:
        pytest.skip("bone's exporter could not run here (FastAPI absent) — "
                    "the contract is UNKNOWN in this environment, not current")
    assert COMMITTED.is_file(), f"{COMMITTED} is missing"
    if COMMITTED.read_text(encoding="utf-8") == fresh:
        return

    # Name the difference rather than "they differ": the artifact is 60 kB and
    # a reader who has to diff it themselves is being sent to do the work twice.
    import difflib

    delta = [l for l in difflib.unified_diff(
        COMMITTED.read_text(encoding="utf-8").splitlines(),
        fresh.splitlines(), "committed", "regenerated", lineterm="", n=1)][:40]
    raise AssertionError(
        "files/anatomy/skills/contracts/bone.openapi.yml is stale — a route "
        "changed and the artifact agents read did not. Regenerate:\n"
        "  python3 files/anatomy/bone/bin/export-openapi.py "
        "--output files/anatomy/skills/contracts/bone.openapi.yml\n\n"
        + "\n".join(delta)
    )
