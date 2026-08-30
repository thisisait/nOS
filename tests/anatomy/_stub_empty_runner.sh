#!/bin/sh
# Stub one_shot runner: always answers "nothing extractable" as a JSON list,
# which is what PHP emits for an empty object. Used by
# test_the_contract_can_express_an_absent_field.py only.
echo '{"chain": [], "stop_reason": "ok"}'
