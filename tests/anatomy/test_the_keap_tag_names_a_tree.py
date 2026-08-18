"""`nos/keap:<tag>` must name a tree, not "whatever the last build produced".

`docs/hidden_fees/12`: the compose fragment carried `image: nos/keap:{{
keap_version }}` with `build:` running on every converge, so the tag was
rewritten in place by each `up -d --build`. It therefore named the most recent
build rather than a source tree, and the two things a version number exists for
both failed:

  * setting `keap_repo_ref` back to an earlier release did NOT get that
    release's image unless it was also rebuilt — the version could not roll back;
  * `git pull` by hand in `~/keap/src` changed what the running container
    ingests immediately, with no rebuild and no signal, because `knowledge/` is
    bind-mounted live while the application code is baked at image-build time.

Resolving the commit into the tag closes both: a different tree is a different
tag, so the image either already exists (and is that tree) or gets built.

THE PART THAT IS EASY TO UNDO WITHOUT NOTICING, and the reason this is a gate
rather than a comment: `{{ keap_image_tag | default(keap_version) }}` looks like
defensive good practice and is the whole defect restored. The fact is set from
`git rev-parse` in `tasks/main.yml`; the passes where it is missing are exactly
the passes where someone is iterating with `--tags`, which is exactly when a
silent fallback to the bare version would rebuild the ambiguity unseen. A
missing fact must be a loud render failure.

WHAT THIS GATE DOES NOT DO: it does not check that the built image's labels
match the checkout, and it cannot — CI has no Docker daemon and no KEAP clone.
Entry 12's second, independent close (a version handshake before `ingest.mjs`,
which KEAP has offered as `knowledge/version-check.mjs`) remains unclaimed and
is the one that would catch a live skew rather than prevent a stale tag.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO / "roles/pazny.keap/templates/compose.yml.j2"
TASKS = REPO / "roles/pazny.keap/tasks/main.yml"


def test_the_files_this_gate_describes_exist():
    """Positive control — a renamed role makes every check below vacuous."""
    assert COMPOSE.is_file(), "roles/pazny.keap/templates/compose.yml.j2 is gone"
    assert TASKS.is_file(), "roles/pazny.keap/tasks/main.yml is gone"
    assert "image: nos/keap:" in COMPOSE.read_text(encoding="utf-8"), (
        "the compose fragment no longer tags a nos/keap image at all"
    )


def test_the_tag_carries_a_resolved_commit():
    src = COMPOSE.read_text(encoding="utf-8")
    match = re.search(r"^\s*image:\s*nos/keap:(.+)$", src, re.M)
    assert match, "no `image: nos/keap:…` line found"
    tag = match.group(1).strip()
    assert "keap_image_tag" in tag, (
        f"the image tag is {tag!r}, which does not use `keap_image_tag`. A tag "
        "built from the version alone is rewritten in place by every "
        "`up -d --build`, so it names the last build and not a tree."
    )


def test_the_tag_has_no_silent_fallback():
    """A `| default(keap_version)` here restores the entire defect while reading
    as caution — which is why it is worth a test of its own."""
    src = COMPOSE.read_text(encoding="utf-8")
    match = re.search(r"^\s*image:\s*nos/keap:(.+)$", src, re.M)
    assert match
    tag = match.group(1)
    assert "default(" not in tag, (
        f"the image tag {tag.strip()!r} falls back when `keap_image_tag` is "
        "unset. The passes where the fact is missing are the `--tags` passes "
        "where someone is iterating, so the fallback would restore the "
        "ambiguity exactly when nobody is looking for it. Let the render fail."
    )


def test_the_commit_is_read_from_the_checkout_not_the_clone_result():
    """`_keap_clone.after` is undefined whenever the clone task did not run this
    pass — `--tags keap` on an existing checkout, check mode, a skipped `when`.
    Keying the tag on it would make the tag depend on whether a clone happened
    rather than on what is on disk."""
    src = TASKS.read_text(encoding="utf-8")
    assert "git rev-parse" in src, (
        "the commit is no longer read from the checkout. If it now comes from "
        "the git module's registered result, the tag is undefined on every "
        "pass that did not re-clone."
    )
    assert "keap_image_tag" in src, "tasks/main.yml no longer sets keap_image_tag"
    assert "check_mode: false" in src, (
        "the rev-parse no longer runs in check mode, so `--check` would fail to "
        "render the compose fragment rather than reporting what it would do."
    )
