"""Anatomy gate: the fs object id may not be changed on the organ side alone.

WHY THIS EXISTS. Roadmap row `kpro-ids` ("A cortex id that survives a file being
moved") points at `files/anatomy/cortex` and asks for `fs:<uid>:sha1(relPath)`
to become an opaque id with the path as an attribute. Doing that HERE is the
wrong tree, and the estate has a live consumer that proves it rather than a
preference:

  * `server/cortex-fs.ts` says of the two root shapes that they "produce the
    same relPath, and therefore the same `fs:<uid>:<sha1(relPath)[:16]>` ids the
    container derives through the nested mount. That id equality is the whole
    point: it is what makes the two corpora comparable at all."
  * `files/anatomy/scripts/cortex-corpus-diff.py` cashes that sentence every
    night: it compares the two fs id SETS exactly (`knowledge_objects[fs:]`) and
    reports the verdict as the `fs ids` clause. `~/.nos/cortex-corpus-diff.json`
    records that clause as the estate's own reading.
  * A removal-shaped disagreement HALTS `cortex-fs-sync`. So re-minting ids in
    the organ without KEAP does not merely diverge: every id moves at once, the
    harness reads it as the whole corpus vanishing, and the nightly sync refuses
    to run.

So `kpro-ids` lands in KEAP first and is re-vendored. This gate is the tripwire
for the next agent handed that row, because the row names only this repo.

WHAT IT PINS is the artifact — the two id expressions as they appear in the
vendored source, and the fact that the nightly harness still consumes them. Not
prose about them: a comment claiming id equality is not id equality.

WHEN THE UPSTREAM CHANGE LANDS, this gate is the thing to edit deliberately, in
the same commit as the re-vendor.

NOT COVERED, and it is the finding worth carrying: an opaque id does not by
itself survive a move. The filesystem is the authority here and the syncer sees
only snapshots, so identity is re-derived every pass — look a minted id up by
`(uid, path)` and a moved file still finds no row, mints a new one, and the old
one is pruned. Move survival needs move ADOPTION (a move-invariant signal such
as the inode, which `lstatSync` already returns), and the id format is the
cosmetic half of that work, not the mechanism.
"""

from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
FS_SYNC = REPO / "files/anatomy/cortex/server/fs-sync.ts"
HARNESS = REPO / "files/anatomy/scripts/cortex-corpus-diff.py"

#: The users pass and the mapped-folder pass, each minting from the RELATIVE
#: PATH. Whitespace-tolerant, everything else literal — a change of hash, of
#: length, or of the hashed input is exactly what must go red.
USERS_ID = re.compile(
    r"`fs:\$\{f\.uid\}:\$\{crypto\s*\.?\s*createHash\('sha1'\)\s*"
    r"\.update\(f\.relPath\)\s*\.digest\('hex'\)\s*\.slice\(0,\s*16\)\}`"
)
MAPPING_ID = re.compile(
    r"`fsm:\$\{m\.id\}:\$\{crypto\s*\.?\s*createHash\('sha1'\)\s*"
    r"\.update\(f\.relPath\)\s*\.digest\('hex'\)\s*\.slice\(0,\s*16\)\}`"
)


def test_users_pass_id_is_still_sha1_of_the_relative_path():
    assert USERS_ID.search(FS_SYNC.read_text(encoding="utf-8")), (
        "the users-pass fs object id no longer reads `fs:<uid>:sha1(relPath)[:16]`. "
        "If this is kpro-ids: it belongs in KEAP and arrives here by re-vendor, "
        "because cortex-corpus-diff.py compares the two id sets exactly every night "
        "and a wholesale re-mint reads as the corpus being deleted."
    )


def test_mapping_pass_id_is_still_sha1_of_the_relative_path():
    assert MAPPING_ID.search(FS_SYNC.read_text(encoding="utf-8")), (
        "the mapped-folder fs object id no longer reads `fsm:<mapping>:sha1(relPath)[:16]`. "
        "Same rule as the users pass — KEAP first, then re-vendor."
    )


def test_the_nightly_harness_still_compares_those_ids():
    """The half that makes the two above load-bearing rather than nostalgic.

    A frozen id scheme with nothing reading it is ceremony; the reason it may
    not move unilaterally is that this clause exists.
    """
    source = HARNESS.read_text(encoding="utf-8")
    assert '"knowledge_objects[fs:]"' in source, (
        "cortex-corpus-diff.py no longer compares the fs object id sets — the "
        "constraint the two gates above enforce has lost its consumer, so either "
        "restore the comparison or retire all three together."
    )
    assert '"fs ids"' in source, "the `fs ids` clause is gone from the nightly verdict"
