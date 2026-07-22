"""The mount preflight must not diagnose what it did not distinguish.

Live 2026-07-22, first converge after `nos --remove=all --leave`: the probe
failed because `remove=all` had pruned every image and `alpine:3` was gone —
and the operator was told, with a specific remedy, that Docker Desktop's VM
held a stale /host_mnt reference. The file HAD already computed
`_ext_probe_stale` to tell the two apart; the failure message ignored it.

The trap this closes is worse than a wrong sentence: the prescribed remedy
(restart Docker Desktop) takes long enough that the image pull succeeds on the
retry, so the run then passes — and the operator concludes the false diagnosis
was right. A misdiagnosis that appears to be cured by its own remedy will never
be reported.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "tasks" / "stacks" / "docker-external-mount-preflight.yml"


def _tasks():
    """Every task in the file, including those nested in blocks."""
    out = []

    def walk(items):
        for t in items or []:
            out.append(t)
            for key in ("block", "rescue", "always"):
                if key in t:
                    walk(t[key])

    walk(yaml.safe_load(SRC.read_text()))
    return out


def _fail_tasks():
    return [t for t in _tasks() if "fail" in t or "ansible.builtin.fail" in t]


def _msg(task) -> str:
    body = task.get("fail") or task.get("ansible.builtin.fail") or {}
    return str(body.get("msg", ""))


def _when(task) -> str:
    w = task.get("when", [])
    return " ".join(w) if isinstance(w, list) else str(w)


def test_stale_mount_diagnosis_requires_the_stale_classification():
    """Only a probe failure classified stale may claim the stale-mount cause."""
    accusing = [
        t
        for t in _fail_tasks()
        if "stale /host_mnt" in _msg(t) or "remounted AFTER Docker" in _msg(t)
    ]
    assert accusing, (
        "no task carries the stale-mount diagnosis any more — if it moved, "
        "move this gate with it rather than deleting the pin"
    )
    for t in accusing:
        assert "_ext_probe_stale" in _when(t), (
            f"task {t.get('name')!r} asserts the stale-mount cause without "
            "requiring _ext_probe_stale in its when: — it will accuse the VM "
            "for ANY probe failure, including a missing probe image (which is "
            "the normal state right after remove=deep|all pruned all images)"
        )


def test_non_stale_failure_has_its_own_honest_message():
    """A probe failure that is NOT stale must still fail — loudly, and vaguely.

    Fail-closed: an unclassified failure may not pass silently. But the message
    must not invent a cause, and must not prescribe the Docker restart.
    """
    others = [
        t
        for t in _fail_tasks()
        if "not (_ext_probe_stale" in _when(t) or "not _ext_probe_stale" in _when(t)
    ]
    assert others, (
        "a probe failure without the stale signature has no failure path: it "
        "either falls through silently (missing evidence read as success) or "
        "lands on the stale-mount message it does not fit"
    )
    for t in others:
        msg = _msg(t)
        assert "stale /host_mnt" not in msg, (
            "the non-stale failure repeats the stale-mount diagnosis"
        )
        assert "rc" in msg and "stderr" in msg, (
            "the non-stale failure must show the operator the actual evidence "
            "(rc + stderr) instead of a guess"
        )


def test_probe_image_is_pulled_before_it_is_used_as_the_test():
    """An absent probe image must not be reported as a mount failure.

    `remove=deep|all` prunes every image, so the first converge after a
    teardown ALWAYS starts with the probe image absent.
    """
    names = [str(t.get("name", "")) for t in _tasks()]
    pull_idx = [i for i, n in enumerate(names) if "probe image is present" in n]
    probe_idx = [i for i, n in enumerate(names) if "can the Docker VM bind-mount" in n]
    assert pull_idx, (
        "no explicit probe-image pull: `docker run` pulls implicitly, so a "
        "registry/image problem and a mount problem become the same rc"
    )
    assert probe_idx, "the bind-mount probe task is gone"
    assert min(pull_idx) < min(probe_idx), (
        "the probe image is pulled after the probe that depends on it"
    )


# ── The skipped-task-still-registers trap ────────────────────────────────────
# Live 2026-07-22: the self-heal block's re-probe registered the SAME var as the
# first probe. Ansible registers skipped tasks too — as {skipped: true}, with no
# `rc` — so on every run where self-heal did not fire, the healthy probe's
# result was replaced by a skip, `rc | default(1)` read 1, and the preflight
# failed on a working mount. Every time. Nobody noticed because the probe only
# arms when nos_data_root is under /Volumes, which had never been true.


def test_no_register_name_is_written_by_two_tasks():
    """Two tasks sharing a register name silently overwrite each other.

    Harmless when both always run; a trap the moment one is conditional — the
    skip result wins and carries none of the fields the readers expect.
    """
    seen = {}
    for t in _tasks():
        reg = t.get("register")
        if not reg:
            continue
        seen.setdefault(reg, []).append(str(t.get("name", "<unnamed>")))
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dupes, (
        "these register names are written by more than one task; if either is "
        "conditional, a skip result (no rc/stdout/stderr) overwrites the real "
        "one:\n"
        + "\n".join(f"  {k}: {v}" for k, v in dupes.items())
    )


def test_readers_use_the_reconciled_result_not_a_raw_probe():
    """Failure conditions must read the reconciled fact, not a raw register.

    Scoped to CONSUMERS (fail conditions and their messages), not to the file
    text: the reconciling set_fact legitimately reads both raw registers — that
    is its entire job. A gate that forbade the string everywhere would forbid
    the fix.
    """
    offenders = []
    for t in _fail_tasks():
        for where, text in (("when", _when(t)), ("msg", _msg(t))):
            if "_ext_probe.rc" in text or "_ext_probe.stderr" in text:
                offenders.append(f"{t.get('name')!r} ({where})")
    assert not offenders, (
        "these failure consumers read the raw probe register instead of the "
        "reconciled _ext_probe_rc/_ext_probe_err — they will read the wrong "
        "probe when the self-heal branch runs, or a skip result when it does "
        "not:\n  " + "\n  ".join(offenders)
    )
