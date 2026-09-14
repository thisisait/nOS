"""Anatomy CI gate — apps_runner pre-flight asks the local image cache first.

`docker manifest inspect` is a registry round-trip. Sequential over every
Tier-2 image cost ~34s even when the daemon already had the layers. Local
cache is a valid resolution (compose-up will find the image), so the role
must `docker image inspect` `_apps_images` first and `manifest inspect` only
the local-miss set.

Parse the task file. Do not talk to Docker.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
TASKS = REPO / "roles" / "pazny.apps_runner" / "tasks" / "main.yml"


def _walk(tasks) -> list[dict]:
    out: list[dict] = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        out.append(t)
        for key in ("block", "rescue", "always"):
            out.extend(_walk(t.get(key)))
    return out


def _cmd(task: dict) -> str:
    return str(task.get("ansible.builtin.command") or task.get("command") or "")


def _loop(task: dict) -> str:
    return str(task.get("loop") or "")


def test_image_inspect_of_apps_images_precedes_manifest_inspect():
    tasks = _walk(yaml.safe_load(TASKS.read_text(encoding="utf-8")))
    local_i = next(
        (i for i, t in enumerate(tasks)
         if "image inspect" in _cmd(t) and "_apps_images" in _loop(t)),
        -1,
    )
    manifest_i = next(
        (i for i, t in enumerate(tasks) if "manifest inspect" in _cmd(t)),
        -1,
    )
    assert local_i >= 0, (
        f"{TASKS}: no task image-inspects `_apps_images` — pre-flight must "
        "ask the local cache before the registry.")
    assert manifest_i >= 0, f"{TASKS}: no docker manifest inspect task"
    assert local_i < manifest_i, (
        f"{TASKS}: image inspect is task {local_i}, manifest inspect is "
        f"{manifest_i}. Registry-first is the ~34s sequential miss this "
        "gate pins against.")


def test_manifest_inspect_loops_local_misses_not_every_image():
    tasks = _walk(yaml.safe_load(TASKS.read_text(encoding="utf-8")))
    manifest = next(t for t in tasks if "manifest inspect" in _cmd(t))
    loop = _loop(manifest)
    assert "_apps_images" not in loop, (
        f"{TASKS}: manifest inspect still loops `_apps_images` — that is "
        "the registry-first path. Loop the local-miss set instead.")
    assert "rejectattr" in loop and "_apps_image_local_probes" in loop, (
        f"{TASKS}: manifest inspect loop is not the local-miss set "
        f"(expected rejectattr on `_apps_image_local_probes`): {loop}")
