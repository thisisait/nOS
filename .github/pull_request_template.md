## What and why

<!-- The part touched, the symptom, the structural fix. Base branch: dev. -->

## The gate, red then green

<!-- A fix ships with the gate that would have caught it (ssot/doctrine/gates.md).
     Paste the failing run against the old code, then the passing run. -->

- Gate: `tests/...::test_...`
- Red before the fix:
- Green after:

## Checks run

- [ ] `python3 -m pytest tests/anatomy -q` (summary read from a file, not `| tail`)
- [ ] `ansible-playbook main.yml --syntax-check`
- [ ] Converge or smoke, if the change needs one to prove (`--tags verify`, `nos-smoke --strict`): say which, or "not needed" and why

## Threat checklist (docs/review/threat-checklist.md)

<!-- "no findings" or file:line + whether a gate/manifest/plugin declares it. -->

1. What runs got wider:
2. Supply chain:
3. Secrets and credentials:
4. Agent power:
5. Self-review laundering (gate/allow-list/expected value changed with its code?):
6. Session compromise:

- [ ] No `config.yml`, `credentials.yml`, secrets, personal hostnames/paths/emails or organisation names in the diff
