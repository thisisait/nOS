# 06 — Removal answered a question the deploy stopped asking

**Status:** closed 2026-07-22 (guard aligned + parity gate), same-day as billed.

**The fee.** `tasks/removal-set.yml` applied the external-SSD path overrides
whenever `external_storage_root` was non-empty — and it is non-empty **by
default**. The deploy applies the same overrides only under
`configure_external_storage: true` (`main.yml` gate on
`tasks/external-storage.yml`). After the FS-doctrine migration moved the
estate to `~/nos/platform/**` and the flag went false, the two conditions
silently disagreed: data was **written** under one rule and **removed** under
another.

**How it was billed.** First live `nos --remove=data` (2026-07-22): the
removal list pointed at `/Volumes/SSD1TB/*` (mostly `[absent]`), the real
platform data survived, the run regenerated the 7 destructive-group keys, and
Infisical came back up against its surviving DB with a rotated encryption key
— `decryptRootKey: Unsupported state or unable to authenticate data`,
crashloop, STRICT health gate red. Worse: the **R5 post-removal verify was
green** — it measured the same wrong list, so it certified the absence of
paths nobody deployed to. The check measured a different layer than the one
that fails ([doctrine/gates.md](../doctrine/gates.md)).

**Why nobody was looking.** The guard was inherited byte-identical from
blank-reset's section 0, where it had been *correct for years* — because back
then the estate really lived on the SSD, so both conditions happened to agree.
The FS-doctrine migration changed the deploy's answer and nothing re-asked the
removal's. Nothing failed (blank was never run post-migration — only
uninstall, whose `nos_data_root` wholesale path masked it), and nobody was
looking.

**The rule.** *Whatever condition decides where data is WRITTEN must be the
same condition deciding where it is REMOVED — one gate, two readers.* Pinned
by `tests/anatomy/test_removal_external_guard_parity.py`, which fails if
either side's condition drifts from the other.

**Open residue.** `/Volumes/SSD1TB/{authentik,gitea,bookstack,…}` still holds
the orphaned pre-migration estate copy. No removal level reaches it anymore
(correctly — the deploy doesn't write there). Manual cleanup, or a future
storage-coherence sweep, owns it.
