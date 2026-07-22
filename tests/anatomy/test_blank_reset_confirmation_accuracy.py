"""Anatomy CI gate — blank-reset confirmation prompt must match real behavior.

tasks/blank-reset.yml shows a destructive-op confirmation prompt (the boxed
`pause:` block) BEFORE it wipes the host. The operator reads that box and hits
ENTER trusting that what it says is what happens. Two ways the prompt silently
drifts from reality:

  1. The "All Docker containers and volumes" promise. blank-reset stops each
     compose stack with `docker compose -p <stack> down -v`. If a stack project
     exists (templates/stacks/<stack>/) but is NOT in the down-loop, its
     containers + bind-volumes survive the blank — the box lies. The `apps`
     stack (Tier-2 manifest-driven, `-p apps`) was exactly this gap.

  2. The conditional modifier lines. The box renders different text for the
     plain-blank path vs `flush=deep` (`_flush_deep`). Those claims must track
     where the work actually happens:
       - "Docker images kept" is TRUE for blank (no `image prune` in
         blank-reset.yml); image-prune lives ONLY in flush-deep.yml.
       - The Homebrew cache deep-clean (`brew cleanup -s`) likewise lives ONLY
         in flush-deep.yml, so the blank-path Homebrew line must NOT claim a
         cache clean.

This gate parses the prompt + the deletion tasks + the flush-deep tasks and
fails the moment any of those three couplings drift, so a future edit that
deletes something new (or stops deleting something promised) can't ship without
also correcting the operator-facing box.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
BLANK_RESET = REPO_ROOT / "tasks" / "blank-reset.yml"
FLUSH_DEEP = REPO_ROOT / "tasks" / "flush-deep.yml"
STACK_TEMPLATES_DIR = REPO_ROOT / "templates" / "stacks"


def _blank_src() -> str:
    return BLANK_RESET.read_text()


def _flush_src() -> str:
    return FLUSH_DEEP.read_text()


def _real_compose_stacks() -> set[str]:
    """Authoritative set of compose stack projects (one dir per stack)."""
    return {
        p.name
        for p in STACK_TEMPLATES_DIR.iterdir()
        if p.is_dir() and (p / "docker-compose.yml.j2").exists()
    }


def _down_loop_stacks() -> list[str]:
    """The stack names listed in the `compose ... -p <item> down -v` loop."""
    src = _blank_src()
    # The down task's loop is the first `loop:` block in the file (the stop task).
    match = re.search(
        r'-p \{\{ item \}\} down -v.*?\n  loop:\n(?P<body>(?:    - \S+\n)+)',
        src,
        re.DOTALL,
    )
    assert match, "could not locate the compose-down stack loop in blank-reset.yml"
    return re.findall(r"    - (\S+)\n", match.group("body"))


def _prompt_block() -> str:
    """The boxed confirmation prompt body (between the box-corner chars)."""
    src = _blank_src()
    match = re.search(r"╔.*?╝", src, re.DOTALL)
    assert match, "confirmation prompt box not found in blank-reset.yml"
    return match.group(0)


# ── 1. "All Docker containers and volumes" promise must cover every stack ──
def test_down_loop_covers_every_compose_stack():
    """Every real compose stack must be in the blank down-loop.

    If a stack project exists but is missing from the loop, the prompt's
    "All Docker containers and volumes will be deleted" is a lie — that
    stack's containers + bind-volumes survive the blank.
    """
    real = _real_compose_stacks()
    looped = set(_down_loop_stacks())
    missing = sorted(real - looped)
    assert not missing, (
        "tasks/blank-reset.yml compose-down loop is missing these compose "
        "stacks (their containers survive blank=true, breaking the "
        "'All Docker containers and volumes' promise):\n  - "
        + "\n  - ".join(missing)
        + "\n\nAdd each to the `down -v` loop."
    )


def test_apps_stack_is_in_down_loop():
    """Regression pin: the `apps` Tier-2 stack must be stopped on blank.

    apps-up.yml deploys `-p apps`; before this fix the down-loop omitted it.
    """
    assert "apps" in _down_loop_stacks(), (
        "the `apps` compose stack must be in the blank-reset down-loop"
    )


def test_down_loop_has_no_phantom_stacks():
    """Every stack the loop tries to stop must be a real compose project.

    A typo'd / removed stack name in the loop is dead weight and erodes trust
    that the loop mirrors the real topology.
    """
    real = _real_compose_stacks()
    phantom = sorted(set(_down_loop_stacks()) - real)
    assert not phantom, (
        "blank-reset down-loop references stacks with no templates/stacks/"
        " dir:\n  - " + "\n  - ".join(phantom)
    )


# ── 2. Docker-image modifier must match where image-prune actually runs ──
def test_blank_does_not_prune_docker_images():
    """The 'Docker images kept' blank claim must be true: no image prune here.

    Comment lines are skipped, matching test_preserved_user_data_is_never_deleted
    below: this file's prose legitimately NAMES the prune command when
    documenting which phase owns it. A gate that cannot tell a task from a
    sentence about a task fails on its own documentation — and the fix an
    author reaches for then is to delete the sentence, which is backwards.
    """
    src = "\n".join(
        ln for ln in _blank_src().splitlines() if not ln.lstrip().startswith("#")
    )
    assert "image prune" not in src, (
        "blank-reset.yml prunes Docker images, but the confirmation prompt's "
        "blank-path modifier claims 'Docker images kept'. Either stop pruning "
        "images in the blank path or correct the prompt."
    )


def test_image_prune_lives_in_flush_deep_only():
    """The flush=deep image-prune claim must be backed by flush-deep.yml."""
    assert "image prune" in _flush_src(), (
        "the prompt's flush=deep modifier says 'Docker images + build cache "
        "(flush=deep)', but flush-deep.yml has no `image prune` task"
    )


def test_prompt_image_modifier_is_flush_deep_gated():
    """The image line must render conditionally on _flush_deep, both branches."""
    prompt = _prompt_block()
    assert "Docker images kept" in prompt, (
        "prompt lost the blank-path 'Docker images kept' modifier"
    )
    # Assert the PROPERTY, not the literal. This used to require the string
    # "remove=deep" — which a remove=all run printed verbatim while wiping at
    # level all (live 2026-07-22). A gate that pins a hardcoded level name
    # certifies the very lie it exists to prevent; the line must RENDER the
    # level it is running at.
    assert "_flush_deep" in prompt, (
        "the Docker-image prompt line must branch on _flush_deep"
    )
    assert "remove=\" ~ (remove" in prompt or "{{ remove" in prompt, (
        "the Docker-image prompt line names a hardcoded level instead of "
        "rendering the actual `remove` value — remove=all would announce "
        "itself as remove=deep"
    )


# ── 3. Homebrew cache-clean modifier must match where it actually runs ──
def test_blank_does_not_deep_clean_homebrew_cache():
    """Plain blank must NOT run `brew cleanup` — that is a flush=deep action."""
    assert "brew cleanup" not in _blank_src(), (
        "blank-reset.yml runs `brew cleanup` but the cache deep-clean is meant "
        "to be a flush=deep-only behavior; the blank-path Homebrew prompt line "
        "must not promise a cache clean"
    )


def test_homebrew_cache_clean_lives_in_flush_deep_only():
    """The Homebrew cache deep-clean belongs to flush-deep.yml."""
    assert "brew cleanup" in _flush_src(), (
        "flush-deep.yml lost its `brew cleanup` cache deep-clean task"
    )


def test_prompt_homebrew_modifier_is_flush_deep_gated():
    """Homebrew line must branch on _flush_deep and tell the truth per path.

    Blank path: packages + cache KEPT (services just restart).
    flush=deep:  packages kept, cache cleared.
    """
    prompt = _prompt_block()
    assert "_flush_deep" in prompt, (
        "the Homebrew prompt line must branch on _flush_deep so it tells the "
        "truth for both the blank and flush=deep paths"
    )
    # Blank-path branch must not claim a cache clean for the default blank.
    assert "Homebrew packages and cache" in prompt, (
        "blank-path Homebrew line must state packages AND cache are kept"
    )
    # The deep branch must own the cache-clear claim. Phrased without a
    # hardcoded level for the same reason as the image line above: remove=all
    # also clears the cache, so naming "remove=deep" here was false at level
    # all (live 2026-07-22).
    assert "also clears the cache" in prompt, (
        "the deep-path Homebrew line must own the cache-clear claim"
    )
    assert "remove=deep also clears" not in prompt, (
        "the Homebrew line hardcodes remove=deep; remove=all clears the cache "
        "too and would be announced under the wrong level"
    )


# ── 4. 'Will remain' user-data dirs must NOT appear in any deletion task ──
def test_preserved_user_data_is_never_deleted():
    """Every 'Will remain' path in the prompt must not be wiped by blank-reset.

    The prompt promises ~/media, ~/calibre, ~/.ollama survive. If a future edit
    adds one of those to a `state: absent` / `rm -f` task, the promise breaks.
    (~/.ollama is wiped ONLY by flush-deep with flush_ollama=true — opt-in, and
    that file is not parsed here.)
    """
    # Skip YAML comment lines (the file header documents `rm -rf ~/.ollama` as a
    # MANUAL operator action — it is prose, not a task).
    lines = [
        ln for ln in _blank_src().splitlines() if not ln.lstrip().startswith("#")
    ]
    for preserved in ("/media/", "/calibre/", "/.ollama"):
        # A bare token like "/.ollama" must not be the target of a removal task.
        # We look for it adjacent to a deletion verb on the same logical line.
        offenders = [
            ln
            for ln in lines
            if preserved in ln and ("state: absent" in ln or "rm -f" in ln or "rm -rf" in ln)
        ]
        assert not offenders, (
            f"prompt promises '{preserved}' remains, but blank-reset.yml has a "
            f"deletion task targeting it:\n  " + "\n  ".join(offenders)
        )


# ── The COMPLETION banner, not just the ENTER box ────────────────────────────
# 2026-07-22, first live `nos --remove=all --leave --confirm`: the ENTER box had
# been reworded to the ladder (C5.1) but the closing banner still read "BLANK
# RESET COMPLETE … Playbook now continues with clean installation" — wrong level
# AND a promise `--leave` cancels. The gate above pinned the box the rewording
# touched; the banner it did not touch was unpinned, so the drift shipped green.
# Rule: pin BOTH ends of a ceremony — an accurate opening and a lying closing
# are the same defect.


def _completion_banner() -> str:
    """The text of the closing banner task, or fail loudly if it is gone."""
    src = _blank_src()
    marker = "[BLANK] Data removal complete"
    assert marker in src, (
        "blank-reset.yml has no completion-banner task named "
        f"'{marker}' — renamed or deleted. If the banner moved, move this "
        "gate with it; do not delete the pin."
    )
    start = src.index(marker)
    return src[start : start + 1400]


def test_completion_banner_names_the_level_not_blank():
    banner = _completion_banner()
    assert "remove" in banner and "upper" in banner, (
        "completion banner does not render the actual remove level — a "
        "remove=deep|all run would announce itself under the wrong name"
    )
    # Assert on the RENDERED banner, not on the file: the task's own comment
    # quotes the legacy wording to record why it was replaced, and a gate that
    # cannot tell prose from live template text fails on its own documentation.
    rendered = "\n".join(
        ln for ln in banner.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "BLANK RESET COMPLETE" not in rendered, (
        "the legacy 'BLANK RESET COMPLETE' wording is back in the banner "
        "itself; it names one ladder level for every level"
    )


def test_completion_banner_honours_leave():
    """`--leave` ends the play — the banner must not promise a reinstall."""
    banner = _completion_banner()
    assert "nos_leaving" in banner, (
        "completion banner ignores nos_leaving: under --remove=all --leave it "
        "tells the operator the playbook 'continues with clean installation' "
        "while main.yml end_plays right after verification (live 2026-07-22)"
    )
    # The unconditional promise must be gone; only the leave=false arm may say it.
    unconditional = [
        ln
        for ln in banner.splitlines()
        if "continues with clean installation" in ln and "nos_leaving" not in banner
    ]
    assert not unconditional, "reinstall promise is not conditioned on leave"


def test_completion_banner_announces_the_quiet_phases():
    """flush-deep prints nothing for minutes; the banner must say so.

    The live run read as a hang: the banner said 'continues with clean
    installation' and then `docker image prune -af` + `brew cleanup` ran silent.
    Silence that the operator was told to expect is progress; unannounced
    silence is indistinguishable from a stuck run.
    """
    banner = _completion_banner()
    assert "_flush_deep" in banner, (
        "banner does not announce the images/caches phase — an operator "
        "reads the following silent minutes as a hang"
    )
    assert "nos_remove_source" in banner, (
        "banner does not announce the source-removal phase"
    )
