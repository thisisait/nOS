"""REM-249 / REM-250 — the SOURCE half, not a live converge.

REM-249: rustfs S3 keys were scheme-v1 concatenations
(`{prefix}_pw_rustfs_access` / `_pw_rustfs_secret`) AND they ARE the access
control — Traefik mode is `none` because signed S3 cannot pass a forward-auth
gate. One leaked sibling reveals the prefix; the prefix yields the bucket
that holds the nightly backup.

The judged loop patch added `MINIO_ROOT_PASSWORD` as an alias of the SAME
weak secret. That is a no-op. The tactical the queue named is intercept +
persist, the vaultwarden/outline shape.

REM-250: nfrastack/freescout 2.2.5 ships app 1.8.235; four GHSAs from
2026-08-29 need app >= 1.8.237, which is image 2.2.7+. The pin must be at
least 2.2.8 (the queue's named head at filing). The APP version inside the
running container is UNVERIFIED until `tools/app-version.py` after a
converge — this gate does not claim that.

WHAT THIS CANNOT DO: rotate the live container or prove the new image's
app version. Those are a nos + a reader. A green here is the SOURCE
shape; a closed queue row still needs the converge.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MAIN = REPO / "main.yml"
STORE = REPO / "templates/secrets.yml.j2"
COMPOSE = REPO / "roles/pazny.rustfs/templates/compose.yml.j2"
CONFIG = REPO / "default.config.yml"
RECIPE = REPO / "upgrades/freescout.yml"


def _lazy_block() -> str:
    main = MAIN.read_text(encoding="utf-8")
    blk = re.search(r"Lazy-regenerate placeholder.*?\n      tags:", main, re.S)
    assert blk, "the lazy-regenerate set_fact task was renamed or removed"
    return blk.group(0)


def test_rustfs_s3_keys_are_lazy_minted_and_persisted() -> None:
    blk = _lazy_block()
    for name in ("rustfs_access_key", "rustfs_secret_key"):
        assert f"{name}:" in blk, (
            f"{name} is not in the lazy-regenerate block — a converge leaves "
            "the scheme-v1 prefix concatenation as the live S3 admin key "
            "(REM-249). The judged MINIO_ROOT_PASSWORD alias is not a fix."
        )
        assert "_pw_" in re.search(rf"{name}: \"(.*)\"$", blk, re.M).group(1), (
            f"{name}'s guard dropped the `_pw_` test — the live value IS "
            "prefix-shaped, so a length-only guard would keep it"
        )
    tpl = STORE.read_text(encoding="utf-8")
    for name in ("rustfs_access_key", "rustfs_secret_key"):
        assert re.search(rf"^{name}:", tpl, re.M), (
            f"{name} is minted but not persisted — the next run reloads the "
            "derived default and mints a new pair, locking every S3 client "
            "out on every converge"
        )
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "MINIO_ROOT_PASSWORD" not in compose, (
        "the judged no-op landed: MINIO_ROOT_PASSWORD aliases the same weak "
        "secret. RustFS reads RUSTFS_ACCESS_KEY / RUSTFS_SECRET_KEY."
    )
    assert "RUSTFS_ACCESS_KEY" in compose and "RUSTFS_SECRET_KEY" in compose


def test_freescout_pin_clears_the_aug29_wave() -> None:
    cfg = CONFIG.read_text(encoding="utf-8")
    pin = re.search(r'^freescout_version:\s*"(\d+\.\d+\.\d+)"', cfg, re.M)
    assert pin, "freescout_version left default.config.yml"
    ver = tuple(int(p) for p in pin.group(1).split("."))
    assert ver >= (2, 2, 8), (
        f"freescout_version is {pin.group(1)}; REM-250 needs >= 2.2.8 "
        "(app 1.8.237+). Do not claim the running app version here."
    )
    recipe = RECIPE.read_text(encoding="utf-8")
    at_target = re.search(
        r'id: "freescout-2.2-current".*?to: "(\d+\.\d+\.\d+)"',
        recipe,
        re.S,
    )
    assert at_target, "the 2.2-current recipe track left upgrades/freescout.yml"
    assert at_target.group(1) == pin.group(1), (
        f"recipe to={at_target.group(1)} but pin={pin.group(1)} — a plain "
        "main.yml re-render would revert the applied hop"
    )
