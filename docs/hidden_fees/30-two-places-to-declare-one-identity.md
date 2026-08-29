# 30 — Two places to declare one identity, and the obvious one is not read

**Found 2026-08-29, by an audit looking for dead config, not for a compliance
defect.**

`default.config.yml` is where an operator sets things. It carried, since the
2026-06-01 gov batch:

```yaml
instance_org: ""                          # Client organization name
gdpr_controller_name: "{{ instance_org | default('') }}"   # Art-30(1)(a) controller identity
gdpr_dpo_name: ""                                          # Art-33(3)(b) DPO
gdpr_dpo_contact: "{{ default_admin_email }}"
```

No task, template, plugin or plist renders any of them. The two consumers —
`tools/gdpr-dpa-register.py` and `files/anatomy/wing/bin/breach-report.php` —
read `GDPR_CONTROLLER_NAME` / `GDPR_DPO_NAME` / `GDPR_DPO_CONTACT` from the
**environment**, and nothing in the estate exports those. So the Article-30
register has said this since the day it was generated:

```
- **Controller:** _(unset — export GDPR_CONTROLLER_NAME)_
- **DPO / contact point:** _(unset — export GDPR_DPO_NAME)_
```

An operator who fills in `instance_org` gets exactly that output. The register
is correct — it names the missing variable — but it names the one they did not
touch, while the field they did touch is inert.

## Why nothing caught it

`tests/anatomy/test_gdpr_register_coverage.py::test_committed_dpa_register_is_current`
clears the three env vars before comparing, with a stated reason: the committed
register is the placeholder form, so a gov operator who exported them must not
hit a spurious red. That is a sound gate for what it guards. It also means the
only test that touches this identity **assumes the env path** and never asks
whether the config path reaches it.

Same shape one file along: `infisical_disable_signup: true` sat in
`default.config.yml` with the comment *"Admin creates all users"*, and no env,
task or template anywhere consumes it. A posture stated in the config file and
applied nowhere.

## The fee

Not "the register is wrong" — it is honest about being unset. The fee is that
the estate offers **two spellings of one declaration** and reads the less
obvious one, so filling in the config file produces a confident, correct-looking
document with the identity missing. For `infisical_disable_signup` the fee is
worse in kind: reading the config file tells you signup is closed, and nothing
closed it.

## What was done, 2026-08-29

Only half. `infisical_disable_signup` was **deleted** — a false claim is worse
than an absence, and its removal restores the honest answer (nobody has
configured this). The four GDPR/identity vars were **kept**: they are the field
an operator should fill, and deleting them loses the intent rather than the
defect.

Owed: one channel. Either the playbook exports the three `GDPR_*` env vars into
whatever runs the register and the breach reporter, or the two vars stop being
offered in `default.config.yml` and the runbook says "export these". Either
closes it; carrying both spellings is what does not.

Owed separately: whether Infisical CE signup is actually open on a live install.
The config never closed it, so nobody knows, and the answer is a converge and a
probe, not a grep.
