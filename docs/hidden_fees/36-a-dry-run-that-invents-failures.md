# 36 — A dry run that invents failures

**Found 2026-08-29, trying to dry-run a change before applying it.**

Two source fixes were ready for the Wing role, so the obvious thing was
`ansible-playbook main.yml --tags wing --check` first. It failed:

```
fatal: frankenphp at /opt/homebrew/bin/frankenphp did not report the
       pinned version 1.12.4 (rc=0).  Reported:
```

`frankenphp --version` on that host prints `FrankenPHP v1.12.4`. Fixed, re-run,
one task further:

```
fatal: Wing daemon did not bind 127.0.0.1:9000 within 20 seconds
```

`curl http://127.0.0.1:9000/` → **403**. The daemon answering, on the port the
message names.

## The mechanism

`command` and `uri` perform nothing under `--check`. The registered result comes
back empty; `_ver.stdout | default('')` and `_probe.status | default(0)` turn
that absence into a measurement of zero; and the refusal below reads the zero as
a verdict.

It is the estate's oldest defect with the sign flipped. The usual form is
absence read as **success** — a probe that goes green by not asking. Here it is
absence read as **failure**, which is not better: a dry run that invents faults
a converge does not have is how an estate learns to stop dry-running, and then
nobody has a net at all.

The fix is one line and already the idiom in 145 places in this tree:
`check_mode: false` on the reading task. A version probe and a GET change
nothing; performing them is the only way a preflight can tell NOT MEASURED from
MEASURED BAD.

## What was done, 2026-08-29

Both reads in `roles/pazny.wing/tasks/main.yml` opt out of check mode.
`--tags wing --check` now completes: **438 ok, 0 failed** — the first successful
dry run of that role.

Gate: `tests/anatomy/test_a_dry_run_gathers_its_own_evidence.py` parses the
role's tasks and refuses any `fail:`/`assert:` whose CONDITION reads a register
filled by a check-blind module. It deliberately ignores the `msg:` body — the
diagnostic there already renders its own `default('(diagnose task skipped)')`,
which is honest, and a first draft that read the message as a condition reported
that as an offence. Retro-verified by deleting each opt-out separately.

## Not closed, and the list is the useful part

The same scan over `roles/` and `tasks/` finds **twenty more** refusals deciding
on evidence a `--check` never gathers:

```
roles/pazny.freescout/post.yml        refuse an ownerless FreeScout
roles/pazny.gitea/post-forge.yml      refuse to clobber a pull-mirror
roles/pazny.gitea/post.yml            SSO guard — refuse a hidden form
roles/pazny.homeassistant/post.yml    refuse if the migration ran
roles/pazny.keap/seed-face-table.yml  fail on a DataTable definition
roles/pazny.keap/selfmodel.yml        WET GATE ×2 — unmeasured sync, dangling anchors
roles/pazny.openclaw/main.yml         Ollama keg/daemon pin ×3
roles/pazny.superset/post.yml         silent password-reset failure ×2
tasks/apply-patches.yml               disk-space precondition
tasks/dnsmasq.yml                     local DNS still down
tasks/removal-verify.yml              fail loudly on any survivor
tasks/restore.yml                     no backups / MariaDB / PostgreSQL ×3
tasks/run-mode.yml                    non-interactive removal without a sudo path
tasks/stacks/authentik_service_post.yml  Portainer SSO not active
```

**None of them was measured**, and that is why none was edited. A full `--check`
of `main.yml` stops at task 29 needing `become`, so nothing here proves any of
those twenty is ever reached in a dry run — and editing twenty files on
suspicion is how a small true finding becomes a large unverified diff. The list
is recorded so the next person to dry-run one of those paths has it.

Worth knowing before acting on it: the `nos --remove` dry run is **not** Ansible
check mode — it is its own inventory-and-exit-0 mechanism — so
`tasks/removal-verify.yml` reads alarming on this list and is not affected in
practice. Checking that took two minutes and is exactly why the other nineteen
should be checked too, one at a time, by whoever needs them.
