"""Anatomy gate: staging a Home Assistant http config without promoting it reverts.

MEASURED, over five days. `home.pazny.eu` answered **400** from 2026-08-06 to
2026-08-11 while the container reported `healthy` and every converge finished
`failed=0`. Nothing in nOS was wrong; nothing in nOS could fix it either.

WHAT HA DID. Recent Home Assistant moved `http:` out of `configuration.yaml`
into `.storage/http`, and the move is one-way — once `yaml_migration_done` is
true, "future starts will ignore any remaining YAML". So the role kept rendering
a correct `configuration.yaml` that HA had stopped reading. A converge could
repeat forever without touching the live value, which is why five days of green
runs produced no change.

WHAT THE STORE HELD. `stable` carried `172.16.0.0/32`, a mask that matches one
address, so Traefik's `172.30.0.55` was an untrusted proxy and every forwarded
request was refused. 7544 log lines said so, and nobody was reading them.

WHY THE OBVIOUS FIX IS HALF A FIX. Clearing `yaml_migration_done` makes HA read
the YAML again — and stage the result as PENDING, on a five-minute trial that
**reverts unless promoted**. Promotion is a websocket call written for a human
at a browser. An unattended converge cannot make it and nOS holds no HA token,
so a role that only clears the flag produces a service that works for five
minutes after every converge and then breaks again — worse than the steady
failure, because it looks fixed while an operator is watching.

HA does have its own repair, `_stable_differs_only_by_lost_proxy_masks`, whose
docstring describes our exact `/12`→`/32` shape. It did not fire: we had also
moved `login_attempts_threshold` from -1 to 10 (REM-168), and that repair
applies only when the configs differ by masks ALONE. Measured from the store,
not assumed — the two values are visible side by side in `stable` and `pending`.

THE LAW PINNED HERE: the two tasks come as a pair. Whoever removes the promotion
gets told why, rather than discovering it five minutes into the next converge.

WHAT THIS CANNOT DO: prove the edge returns 200. That is a live fact and it
belongs to `tools/discovery-scan.py` probe G — which, worth saying, would have
found this on day one had it existed then. Shape here, effect there.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
POST = REPO / "roles/pazny.homeassistant/tasks/post.yml"

STORE = "/config/.storage/http"


@pytest.fixture(scope="module")
def tasks() -> list[dict]:
    return yaml.safe_load(POST.read_text(encoding="utf-8")) or []


def _touching(tasks: list[dict], needle: str) -> list[dict]:
    """Tasks whose rendered body mentions `needle`, whatever the module."""
    out = []
    for task in tasks:
        body = yaml.safe_dump(task)
        if needle in body:
            out.append(task)
    return out


def test_the_role_still_reads_the_store_before_deciding() -> None:
    """The register the two conditionals depend on.

    Without a read there is nothing to be conditional ON, and both tasks would
    either run every converge (restart loop) or never (silent no-op).
    """
    assert STORE in POST.read_text(encoding="utf-8"), (
        f"{POST.relative_to(REPO)} no longer reads {STORE}. That file — not "
        "configuration.yaml — is where a modern HA keeps its http config, and "
        "a role that does not read it cannot know whether it has been applied."
    )


def test_clearing_the_migration_flag_is_paired_with_a_promotion(tasks) -> None:
    """The whole point. One without the other is a five-minute fix."""
    clears = _touching(tasks, "yaml_migration_done")
    promotes = _touching(tasks, "'pending'")

    if not clears:
        pytest.skip(
            "the role no longer clears yaml_migration_done — if HA regained a "
            "YAML path, this gate has nothing to protect. Delete it."
        )

    assert promotes, (
        "the role clears `yaml_migration_done` (making HA re-read the YAML and "
        "stage it as PENDING) but never promotes the result. HA reverts a "
        "pending config after five minutes and restarts. The service will come "
        "up correct, be observed as fixed, and break again unattended — the "
        "worst of the three possible states."
    )


def test_the_promotion_clears_pending_rather_than_only_copying_it(tasks) -> None:
    """A promotion that leaves `pending` set is still on trial.

    Copying pending into stable looks like it worked and changes nothing: HA
    reads `pending` as the config under test, and its revert timer does not care
    what `stable` now says.
    """
    promotes = _touching(tasks, "'pending'")
    if not promotes:
        pytest.skip("no promotion task present; the pairing test above owns that case")

    # Normalised twice before matching, because BOTH of safe_dump's habits broke
    # this assertion on its first two runs: it re-wraps long scalars at ~80
    # columns (splitting the literal across a newline), and it escapes single
    # quotes by doubling them (`''pending''`). Collapsing whitespace and dropping
    # quote characters matches on substance instead of on formatting.
    bodies = " ".join(" ".join(yaml.safe_dump(t).split()) for t in promotes)
    bodies = bodies.replace("'", "").replace('"', "")
    assert "pending, None" in bodies or "pending] = None" in bodies, (
        "the promotion writes `stable` but never clears `pending`. HA treats a "
        "non-null pending as the config on trial and reverts on schedule, so "
        "this promotes nothing while reading as though it did."
    )


def test_both_tasks_are_conditional_so_a_steady_estate_does_not_restart(tasks) -> None:
    """Idempotence, and it is not cosmetic here — each one notifies a restart.

    Unconditional, these two would bounce Home Assistant on every single
    converge, which across the whole playbook is how an estate acquires a
    permanent low-grade churn nobody attributes to anything.
    """
    for needle, label in (("yaml_migration_done", "migration reset"),
                          ("'pending'", "promotion")):
        for task in _touching(tasks, needle):
            assert task.get("when"), (
                f"the {label} task has no `when:`. It notifies a restart, so "
                "unconditional means Home Assistant restarts on every converge "
                "forever — measured green, and wrong."
            )


def test_the_role_does_not_pretend_yaml_still_governs() -> None:
    """The comment that stops the next reader repeating five days of work.

    The failure mode was not subtle code — it was a correct-looking
    `configuration.yaml` that nothing read. Somebody has to say so in the file.
    """
    text = POST.read_text(encoding="utf-8")
    assert "ignore" in text.lower() and "yaml" in text.lower(), (
        "the role no longer records that HA ignores the YAML http block once "
        "migrated. That single fact is what makes a correct-looking "
        "configuration.yaml render irrelevant, and it cost five days."
    )
