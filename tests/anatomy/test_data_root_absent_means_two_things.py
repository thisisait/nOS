"""An absent `nos_data_root` means two different things, and only one is fatal.

  * under `/Volumes/` it is a REMOVABLE disk. Absent = NOT MOUNTED, and creating
    the path manufactures the phantom the cortex mount sentinel exists to catch.
    Hard fail is correct.
  * anywhere else it is an ORDINARY directory on the boot volume. The default is
    `$HOME/nos`, it cannot be "unmounted", and NOTHING in the playbook creates
    it — service data dirs are created individually, deeper, and later.

`pazny.cortex` conflated them, so a DEFAULT-config install failed at that task on
Linux and macOS alike. It passed only for operators who had already redirected
`nos_data_root` onto an existing external disk — which is why a live converge
looked green while the Linux wet-test, on its first non-draft PR run after the
role was Ansible-ized, got 226 tasks in and stopped (2026-08-02).

The discriminator is not invented for this gate: `docker-external-mount-preflight`
already arms on `is match('^/Volumes/')`, and this test pins that the two agree.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CORTEX = REPO / "roles/pazny.cortex/tasks/main.yml"
PREFLIGHT = REPO / "tasks/stacks/docker-external-mount-preflight.yml"
CONFIG = REPO / "default.config.yml"

REMOVABLE_TEST = "is match('^/Volumes/')"


def _tasks(path: Path) -> list[dict]:
    return [t for t in (yaml.safe_load(path.read_text()) or []) if isinstance(t, dict)]


def _when(task: dict) -> str:
    w = task.get("when", "")
    return " AND ".join(w) if isinstance(w, list) else str(w)


def test_the_default_data_root_is_not_removable():
    """If this ever changes, the whole rationale below has to be revisited."""
    text = CONFIG.read_text()
    m = re.search(r"^nos_data_root:\s*(.+)$", text, re.MULTILINE)
    assert m, "nos_data_root not declared in default.config.yml"
    default = m.group(1).strip().strip('"').strip("'")
    assert not default.startswith("/Volumes/"), (
        f"the DEFAULT nos_data_root is {default!r} — if the default is now a "
        "removable volume, the cortex guard's fail-branch becomes the common "
        "case and this gate's reasoning no longer holds"
    )


def test_cortex_distinguishes_removable_from_ordinary():
    tasks = _tasks(CORTEX)

    failing = [
        t for t in tasks
        if ("ansible.builtin.fail" in t or "fail" in t)
        and "data root" in t.get("name", "").lower()
    ]
    assert failing, "the cortex data-root guard disappeared entirely"

    for t in failing:
        assert "removable" in _when(t).lower() or "removable" in t.get("name", "").lower(), (
            f"cortex task {t.get('name')!r} hard-fails on an absent data root "
            "WITHOUT restricting itself to the removable case — that is the "
            "conflation which broke every default-config install"
        )

    # …and the ordinary case must be handled, not merely not-failed.
    creators = [
        t for t in tasks
        if ("ansible.builtin.file" in t or "file" in t)
        and str((t.get("ansible.builtin.file") or t.get("file") or {}).get("path", ""))
        .strip() == "{{ nos_data_root }}"
    ]
    assert creators, (
        "nothing creates nos_data_root for the ordinary (non-removable) case; "
        "not failing is not the same as working"
    )
    for c in creators:
        assert "removable" in _when(c).lower(), (
            "the data-root creator must be gated on NOT-removable, or it will "
            "happily create an unmounted /Volumes path — the phantom itself"
        )


def test_the_removable_discriminator_matches_the_preflight():
    """One test for 'is this an external disk', not two that can drift."""
    for path in (CORTEX, PREFLIGHT):
        assert REMOVABLE_TEST in path.read_text(), (
            f"{path.relative_to(REPO)} no longer uses {REMOVABLE_TEST!r} — the "
            "two places that decide 'is nos_data_root removable' have drifted, "
            "which is how one of them starts guarding a different question"
        )
