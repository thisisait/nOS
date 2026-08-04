#!/usr/bin/env bash
# =============================================================================
# Read ONE key out of Uptime Kuma's `setting` table without creating anything.
#
# WHY THIS IS A FILE AND NOT AN INLINE `docker exec … sqlite3 …`
# -------------------------------------------------------------
# It was inline, and it minted the thing it was reading. `sqlite3 <path> "…"`
# CREATES <path> as an empty database when the path does not exist — so a task
# whose only job was to observe `disableAuth` left a zero-byte `kuma.db` behind.
#
# Measured 2026-08-04 on the live estate: `/app/data/kuma.db`, 0 bytes, dated
# 22:09 — eighty minutes AFTER the container booted at 20:49, i.e. written by
# our converge, not by Kuma. That file is not harmless. Kuma 2's
# `setup-database.js` branches on whether kuma.db is FOUND, so an empty one
# left by a reader is an input to the thing being read.
#
# Same family as the day's other findings, one turn further out: not "a success
# marker written by the code that attempted the work" but "an observation that
# created its own subject". A reader must leave no trace, and the only way to
# be sure of that is to be able to run it against a path that does not exist
# and check the directory afterwards — which is what
# tests/anatomy/test_kuma_reader_creates_nothing.py does, and could not have
# done while this was a quoted string inside a YAML task.
#
# Usage:  read-setting.sh <db-path> <key>
# Output: the value on stdout, or NOTHING at all — for a missing file, an
#         empty file, a missing table, or a missing key. All four are the same
#         answer to the caller ("no setting"), and none is an error.
# Exit:   always 0. A reader that cannot read is not a failure; a CALLER that
#         treats "no answer" as "the answer is false" is, and that is the
#         caller's contract to keep.
# =============================================================================
set -uo pipefail

db_path="${1:?usage: read-setting.sh <db-path> <key>}"
key="${2:?usage: read-setting.sh <db-path> <key>}"

# -s, not -f: a zero-byte file is not a database. Checking existence alone
# would hand sqlite3 the very empty file this script exists to stop creating.
[[ -s "${db_path}" ]] || exit 0

# `file:…?mode=ro` is the belt to -s's braces: even if the file vanishes
# between the test and the call, read-only mode refuses to create it rather
# than helpfully making a new one.
sqlite3 -readonly "${db_path}" \
    "SELECT value FROM setting WHERE key='${key}';" 2>/dev/null || true

exit 0
