#!/bin/bash
# Can codesign use the signing key WITHOUT a dialog? (row storage-genome-codesign-probe)
# A key whose partition list lacks codesign makes `codesign -f` wait on the keychain's "allow?" dialog,
# which nobody answers in a converge: it waited 30+ min (2026-11-12). Signs a throwaway copy of
# /usr/bin/true; no answer in WAIT seconds stops the run with the one command that fixes it.
# A real signing error is left to the sign task, which reports it with its own message.
#   sign-probe.sh <identity sha1> <keychain path> [wait seconds, default 20]
set -euo pipefail
H="$1"; KC="$2"; WAIT="${3:-20}"
probe=$(mktemp -t nos-sign-probe.XXXXXX)
trap 'rm -f "$probe"' EXIT
cp /usr/bin/true "$probe"
# perl's alarm is the timer macOS ships (no coreutils timeout): SIGALRM ends codesign with 142.
rc=$(perl -e 'alarm shift; exec @ARGV' "$WAIT" codesign -f -s "$H" "$probe" >/dev/null 2>&1; echo $?) 2>/dev/null
if [ "$rc" -eq 142 ]; then
  printf '%s\n' "codesign is waiting on a keychain dialog (no answer in ${WAIT} s): the signing key does not let" \
    "codesign use it without asking. Once, in this session (it asks the login password), then re-run:" \
    "  security set-key-partition-list -S apple-tool:,apple:,codesign: -s $(printf %q "$KC")" >&2
  exit 1
fi
