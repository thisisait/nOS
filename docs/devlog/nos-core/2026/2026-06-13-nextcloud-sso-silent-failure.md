---
id: 2026-06-13-nextcloud-sso-silent-failure
title: "Nextcloud SSO was dead — and the playbook never said a word"
date: 2026-06-13
namespace: nos-core
summary: "Nextcloud's Authentik SSO had been silently broken: the user_oidc 8.x app renamed the occ CLI option --mapping-displayname to --mapping-display-name, the registration command failed, and because that task carries failed_when:false + no_log (it handles the client secret) the failure was completely invisible. The playbook reported success, smoke stayed 48/48, and SSO was dead. Fixed the option, and added a loud post-registration verify so this whole class of failure can never hide again."
tags: [nextcloud, sso, authentik, incident, ansible]
actors: [pazny, claude]
related: [tasks/stacks/authentik_service_post.yml]
---
"Does Nextcloud not support SSO?" — the kind of question that sounds like a
docs lookup and turns out to be an incident report. Nextcloud absolutely
supports SSO: it sits in the `native_oidc` bucket, with the `user_oidc` app
configured against Authentik through `occ`. But on the live box, asking
`occ user_oidc:provider` returned **"No providers configured."**

## The Authentik side was perfect

Worth stating, because the OpenTofu cutover is recent and the suspicion fell
there first: the `nextcloud` application existed, the `Nextcloud` OAuth2
provider existed with `client_id=nos-nextcloud`, the discovery endpoint
returned 200 with a valid issuer, and the client secret in Authentik exactly
matched the derived `{global_password_prefix}_pw_oidc_nextcloud`. Tofu did
its job. The break was entirely on the Nextcloud side: the provider was
never registered *into* `user_oidc`.

## The bug: a renamed CLI option behind a no_log wall

The registration task runs `occ user_oidc:provider authentik --clientid=…
--clientsecret=… --mapping-uid=… --mapping-email=… --mapping-displayname=…`.
The `user_oidc` app shipped 8.x and renamed one option:
`--mapping-displayname` → `--mapping-display-name`. The command now exits 1
with *"The --mapping-displayname option does not exist."*

It should have been a one-line fix. What made it a *weeks-long invisible*
break is the task's own guardrails:

```yaml
failed_when: false   # the --update flag differs across user_oidc versions
no_log: true         # the command line carries the client secret
```

Both are individually reasonable — `no_log` keeps the secret out of the log,
`failed_when: false` tolerates version skew in the update subcommand. Together
they turned a hard failure into silence. The playbook reported `failed=0`,
the smoke suite stayed green (it only checks that the URL *responds* — the
Nextcloud login page answers 200 whether or not OIDC is wired), and nobody
was the wiser until someone actually clicked "Log in with Authentik."

## The fix, and the guard that makes it stay fixed

The option rename is the obvious half — corrected in both the active path
(`tasks/stacks/authentik_service_post.yml`) and the plugin hook
(`nextcloud-base/hooks/post_compose.yml`).

The half that matters more is a new **loud verify** task that re-lists the
providers after registration and *fails the play* if `authentik` still isn't
there:

```yaml
- name: "[Authentik->Nextcloud] Verify OIDC provider is registered"
  command: …occ user_oidc:provider
  changed_when: false
  failed_when: "'authentik' not in (_nc_oidc_verify.stdout | default(''))"
```

It carries no secret, so it needs no `no_log`; it just reads state and
asserts. A registration that silently dies now stops the run with a clear
message instead of shipping a dead login. SSO is mandatory in nOS —
the verify makes the playbook hold that line.

## Live result, and a thread left hanging

After the fix, an `iiab`-tagged reconverge registered the provider (ID 1,
`authentik`, `nos-nextcloud`), the verify passed, recap `failed=0`, smoke
48/48.

One honest loose end surfaced while looking: **Gitea's auth source list is
also empty.** That's the same silent-failure *class* but a different and
already-documented saga — the "Gitea SSO lockout, oauth2 source row vanishes"
issue that drove the local-first git pivot to GitLab as the agent forge
surface. It's logged, not forgotten, and deliberately not yanked on here.
