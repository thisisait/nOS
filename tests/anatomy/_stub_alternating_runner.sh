#!/bin/sh
# Alternating stub runner: correct on odd invocations, wrong on even. Counts
# in a file beside itself so successive subprocesses share the state.
# Used by test_a_measurement_can_repeat_itself.py only.
c="${TMPDIR:-/tmp}/nos-alt-runner.count"
n=$(( $(cat "$c" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$c"
if [ $(( n % 2 )) -eq 1 ]; then echo '{"chain": {"v": 1}, "stop_reason": "ok"}'
else echo '{"chain": {"v": 2}, "stop_reason": "ok"}'
fi
