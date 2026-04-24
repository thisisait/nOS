#!/usr/bin/env bash
# Run all Wing State & Migration Framework tests.
set -u

cd "$(dirname "$0")"

FAIL=0
for t in test_*.php; do
    echo "--- $t"
    if ! php "$t"; then
        FAIL=$((FAIL + 1))
    fi
done

if [[ $FAIL -eq 0 ]]; then
    echo "All suites passed."
    exit 0
fi
echo "$FAIL suite(s) failed."
exit 1
