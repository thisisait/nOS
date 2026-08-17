"""A rebuild replaces the site's CONTENTS, never the directory holding them.

MEASURED 2026-08-17, on the first rebuild after pazny.eu went live. The build
cleared its output with `shutil.rmtree(out_dir)` followed by `mkdir`, which is
correct on a developer's machine and wrong on the estate: the web root is
bind-mounted into the nginx container, the mount resolves to an INODE, and the
new directory is a different inode wearing the same name.

What that looked like:

    host:      ~/stacks/iiab/apex-www   index.html, assets/, public-anatomy.json
    container: /usr/share/nginx/html    total 0
    converge:  failed=0, changed=4
    world:     https://pazny.eu -> 403

Nothing errored. The role built the site, the files were there, the container
was healthy, and the public page had been down since the previous task. The
smoke probe was the only thing in the estate that said so — the converge's own
report was, as far as it went, true.

WHAT IS PINNED: that a second build into the same directory leaves the
directory's identity alone. That is the property the mount depends on;
"the files are correct" is not, and was not.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
APEX = REPO / "files/anatomy/apex"


def _build_module():
    sys.path.insert(0, str(APEX))
    import build

    return build


def test_a_rebuild_does_not_replace_the_directory():
    build = _build_module()
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "web-root"

        build.build(out)
        first = out.stat().st_ino
        assert (out / "index.html").is_file(), "the first build wrote no page"

        build.build(out)
        second = out.stat().st_ino

        assert first == second, (
            "the web root was recreated rather than refilled. A running "
            "container's bind mount still points at the old inode, so the "
            "public site goes dark while every check on the host passes."
        )
        assert (out / "index.html").is_file(), "the second build wrote no page"


def test_the_rebuild_actually_replaces_what_is_inside():
    """The counterweight: keeping the directory must not mean keeping stale
    files. A page removed from the build must disappear from the web root."""
    build = _build_module()
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "web-root"
        build.build(out)

        stale = out / "assets" / "left-behind.txt"
        stale.write_text("a file from an older build", encoding="utf-8")

        build.build(out)
        assert not stale.exists(), (
            "a file from the previous build survived the rebuild; the web root "
            "accumulates instead of being replaced, and a withdrawn page stays "
            "fetchable after it is withdrawn."
        )


def test_the_wrong_directory_is_still_refused():
    """Clearing contents in place is more dangerous than removing a directory
    you own, so the guard that refuses a non-apex --out must still hold."""
    import pytest

    build = _build_module()
    import projection

    with tempfile.TemporaryDirectory() as tmp:
        victim = pathlib.Path(tmp) / "someones-documents"
        victim.mkdir()
        (victim / "thesis.md").write_text("years of work", encoding="utf-8")

        with pytest.raises(projection.GateError, match="does not look like"):
            build.build(victim)

        assert (victim / "thesis.md").is_file(), (
            "the build emptied a directory that was not a previous site build"
        )
