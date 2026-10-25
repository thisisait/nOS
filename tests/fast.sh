#!/usr/bin/env bash
# tests/fast.sh — the offline suite in N parallel shards (CI's own split, tests/_shard.py).
#
# 2026-10-24: tests/anatomy took 20-21 min serially on a 14-core host, so the full run
# was skipped or run once at the end. Same tests, same split as CI, one process per shard.
# Exit is the WORST shard's, never a `| tail` (memory local-pytest-false-green); each
# shard's log stays in $out for the failures.
#
#   tests/fast.sh                          # tests/anatomy, shards = cores / 2 (NOS_PYTEST_SHARDS)
#   tests/fast.sh tests -k paperclip   # any pytest args after the path
set -uo pipefail
cd "$(dirname "$0")/.."   # tests/fast.sh lives beside _shard.py, runs from the repo root
n="${NOS_PYTEST_SHARDS:-$(( $(sysctl -n hw.ncpu 2>/dev/null || nproc) / 2 ))}"  # half: at cores-2 the profile-builder sweep's 60 s budget failed (88.7 s) under contention
[ "$n" -ge 1 ] || n=1
[ $# -gt 0 ] || set -- tests/anatomy
out="$(mktemp -d "${TMPDIR:-/tmp}/nos-fast.XXXXXX")"
start=$(date +%s)
# Files that run cargo share each crate's target/ dir: two shards compiling it at once
# raced ("can't find crate for nos_contract", 2026-10-25). They run together, in one
# process of their own; every other file goes to the shards.
cargo_files=$(grep -l -E '"cargo"|cargo (test|build)' tests/anatomy/test_*.py 2>/dev/null)
ignore=(); for f in $cargo_files; do ignore+=("--ignore=$f"); done
python3 -m pytest -q -p no:cacheprovider $cargo_files > "$out/shard-cargo.log" 2>&1 &
for k in $(seq 1 "$n"); do
  NOS_PYTEST_SHARD="$k/$n" python3 -m pytest -q -p no:cacheprovider "$@" "${ignore[@]}" > "$out/shard-$k.log" 2>&1 &
done
rc=0
for job in $(jobs -p); do wait "$job" || rc=$?; done
grep -h -E "^(FAILED|ERROR) " "$out"/shard-*.log | sed 's/ - .*//' | sort -u
python3 - "$out" <<'PY'
import pathlib, re, sys
tot = {}
for f in sorted(pathlib.Path(sys.argv[1]).glob("shard-*.log")):
    lines = [ln for ln in f.read_text(errors="replace").splitlines() if re.search(r"\d+ (passed|failed|error)", ln)]
    if not lines:
        print(f"{f.name}: NO SUMMARY (crashed?)"); tot["broken"] = tot.get("broken", 0) + 1; continue
    for n, word in re.findall(r"(\d+) (passed|failed|skipped|errors?|warnings?)", lines[-1]):
        tot[word] = tot.get(word, 0) + int(n)
print("total: " + ", ".join(f"{v} {k}" for k, v in sorted(tot.items())))
PY
echo "$n shards in $(( $(date +%s) - start )) s, rc=$rc, logs: $out"
exit "$rc"
