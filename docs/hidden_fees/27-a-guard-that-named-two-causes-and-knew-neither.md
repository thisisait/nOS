# 27 — A guard that named two causes and could act on neither

**Found 2026-08-23 by a converge dying at `ok=576 changed=36 failed=1`.**

```
TASK [[tofu-authentik] REFUSE apply — plan would destroy resources]
fatal: tofu plan would destroy/replace 2 resource(s) — refusing to apply.
Two known causes: (a) the tenant is only partially authored in HCL …
(b) a service flipped enabled→false (install_* off) and dropped out of the
registry filter — review the plan, then run the supervised apply below.
```

The two resources:

```
module.service["superset"].authentik_application.this
module.service["superset"].authentik_provider_oauth2.this[0]
```

## The fee

**The guard knew both causes by name and could distinguish neither.** It
counted deletes and stopped. Every occurrence of cause (b) — a normal,
authorised, already-decided removal — cost a failed converge and a hand-run
`tofu apply`.

Cause (b) is not a defect. `install_superset: false` had been in `config.yml`
for two days, with its reasoning written into the file beside it. The same flag
had already caused this same playbook to stop and remove the container
(`prune_disabled_overrides`). The Authentik application and OAuth2 provider
exist **only** to front that container.

So the guard was asking for one decision twice — and CLAUDE.md already states
the rule it was breaking, about the compose prune:

> an opt-in flag that authorises removing a compose fragment also authorises
> stopping the container that fragment described — same decision, not a further
> one.

## Why it looked fine for two months

Because on this estate cause (b) is rare: services get turned on, not off. The
guard was written during the June cutover, when the live risk was a
**partially-authored tenant** — cause (a), where refusing is exactly right. It
was correct for the case it was born in and untested against the other one it
had itself written down.

And the failure was *loud and helpful* — it printed the addresses, the reason,
and a paste-able recovery command. A guard that fails helpfully is much harder
to notice as wrong than one that fails obscurely.

## What closes it

`nos_tofu_destroy_split` attributes each delete to a service, using the
registry's own `enabled` expression — which `lookup('template')` has already
resolved, so no flag-name guessing:

| plan wants to delete | verdict |
| --- | --- |
| `module.service["x"]…`, `install_x` resolves **off** | authorised — applies |
| `module.service["x"]…`, `x` is **enabled** | refuses |
| `module.service["x"]…`, `x` **not in the registry** | refuses — un-authored, not disabled |
| an address naming no service module | refuses — cannot be attributed |

**Fail-closed on everything it cannot account for.** That is what makes the
relaxation safe and it is where the gate spends most of its assertions: the
three ways to be unexplained each get their own test, and each must refuse
*with a stated reason*.

The refusal and the apply now read the **same** predicate. Pinned, because a
mismatch there is the nastiest possible outcome — the run would either apply
what it just refused, or plan an authorised removal, report it, and silently
skip it.

**Verified against the plan that actually failed**, not a synthetic one:
103 resource changes, both superset deletes attributed to a flag that is off,
zero unexplained → the run would now apply. (That first verification was itself
wrong in a way worth reading — see below.)

## The fix failed once, the same way, and that is worth more than the fix

The first cut of the attribution task read
`tofu_authentik_services | default([])`. That name is loaded **task-scoped**,
on the tfvars render 140 lines earlier, deliberately and with the reason
written above it — persisting it play-wide makes `nos_state`'s
`role_vars: "{{ vars }}"` eager-finalize choke. So in the new task it was
undefined, the fallback answered with an empty list, and every destroy came
back *"no `superset` in the registry — un-authored, not disabled"*.

The guard refused **harder** than before, for a reason with nothing to do with
the plan.

Two mistakes, and both are ones this repository already has gates for:

1. **A constant fallback standing in for a value that must be loaded.** Exactly
   [23](23-a-pin-that-never-rendered.md) — and `test_a_role_default_is_not_read
   _across_roles.py`, written the day before, encodes precisely this rule. It
   scans `roles/*/`. This bug was in `tasks/`.
2. **Verified against the source file instead of the artifact.** The check ran
   `nos_tofu_destroy_split` against `state/tofu-authentik-services.yml`, which
   of course contains superset — while the code reads a **variable** that did
   not. The template said one thing and the render said another, which is the
   whole content of fee 23, committed thirty hours earlier.

The second verification did it properly: `terraform/authentik/nos.auto.tfvars.json`,
produced by that same `lookup('template')` load, holds **39 of the registry's
44** services with superset correctly filtered out. That proves the load path
resolves `enabled` from the live flags — evidence from an artifact the estate
produced, not from the file I hoped it read.

**Both halves are now closed.** The task carries its own `vars:` block, there is
no `| default()` on the registry at all, and an unloadable registry returns a
verdict that names *itself*:

> the service registry did not load — this is a WIRING fault in the guard, not
> a fact about this plan

New gate `test_a_task_scoped_var_stays_in_its_task.py`: within one task file, a
name declared on a **leaf** task may not be read by another. A `vars:` on a
**block** is inherited and is explicitly fine — the first cut of that gate
missed the distinction and reported fifteen correct uses of `_tf_dir` as
offenders. Proven in the failing direction against the exact broken form.

## What is still owed

- **An authorised destroy is still a destroy.** It is announced in the
  diagnostic and then done. That is the right trade here — the flag is the
  authorisation and the objects are recreated from the registry if the flag
  goes back on — but it is a trade, not a free lunch.
- **Nothing checks that the *container* is actually gone** before removing its
  SSO objects. Today `prune_disabled_overrides` handles that on the same flag,
  so the two agree by construction; if the prune is ever off while the flag is
  false, this would strip SSO from a running service.
- **The `enabled` expression is trusted to name one flag.** A registry entry
  computing `enabled` from two variables would be read by the resolved value —
  which is correct — but the failure message would name no flag to flip.
