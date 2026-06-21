#!/usr/bin/env bash
# =============================================================================
# nos-boot-id.sh — echo a stable per-boot identifier (changes on every reboot).
#
# Shared by the macOS-as-managed-upgrade continuation flow (arm + resume) so the
# "has the host rebooted since we armed?" check uses ONE source of truth. Mirrors
# the boot-id the upgrade-engine reboot-required marker uses.
#   - macOS:  kern.boottime epoch seconds (the moment of last boot).
#   - Linux:  /proc/sys/kernel/random/boot_id (a fresh UUID each boot).
# Prints the id to stdout; never fails the caller (echoes 'unknown' on miss).
# =============================================================================
set -uo pipefail

case "$(uname -s)" in
  Darwin)
    # kern.boottime prints `{ sec = <boot-epoch>, usec = <micros> } <date>`.
    # The FIRST integer is the boot epoch (seconds). The anchored sed grabs it —
    # a greedy match anchored on the LAST `sec =` wrongly captures usec, and
    # `grep -o … | head` either prints every number (-m1 limits lines, not
    # matches) or SIGPIPEs under pipefail.
    bt="$(sysctl -n kern.boottime 2>/dev/null | sed -E 's/^[^0-9]*([0-9]+).*/\1/')"
    echo "${bt:-unknown}"
    ;;
  *)
    cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown
    ;;
esac
