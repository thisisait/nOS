# nOS — Security & data-protection baseline (DPO one-pager)

> Hand this to a Data Protection Officer at audit time. It is the plain-language
> summary of *how* nOS protects personal data; the per-service **Record of
> Processing Activities** (GDPR Art. 30) lives in
> [`state/dpa-register.md`](../state/dpa-register.md), generated from the same
> source-of-truth and pinned by CI.

nOS is **self-hosted on the operator's own hardware**. There is no nOS SaaS, no
telemetry phone-home, and — absent a processor explicitly declared in the DPA
register — **no third-party data processor and no transfer outside the EU**.
The operator is the data controller; this document and the DPA register are the
controller-side evidence.

## 1. Encryption

| Layer | Mechanism | Custody / responsibility |
|---|---|---|
| **In transit** | TLS terminated at the Traefik edge (wildcard cert: mkcert on `*.local`, Let's Encrypt DNS-01 on a public TLD). No plaintext on the wire between client and edge. | Playbook-managed (`roles/pazny.traefik`, `roles/pazny.acme`). |
| **In transit (internal)** | Service-to-service traffic stays on private Docker networks on a single host; not exposed off-box. | Playbook-managed. |
| **At rest (disk)** | Full-disk encryption — **FileVault** (macOS) / **LUKS** (Linux). | **Operator-provisioned** — nOS does not enable it for you; verify before processing personal data. |
| **At rest (secrets)** | Secrets held in **Infisical** (central vault) or launchd/systemd environment, never written to disk in plaintext by the playbook. See [`secret-lifecycle-doctrine.md`](secret-lifecycle-doctrine.md). | Playbook-managed; root key custody is the operator's. |

## 2. Access control & identity

- **Single sign-on** via Authentik (`auth.<tld>`); every service is gated by one
  of three modes (native OIDC, header-forwarded, or forward-auth). Trichotomy
  and per-user attribution doctrine: [`sso-and-attribution.md`](sso-and-attribution.md).
- **RBAC** — four tiers (admin / manager / user / guest) bound to Authentik
  groups. A service is reachable only by its declared tier.
- **Audit trail** — every privileged action carries an `actor_id` +
  `actor_action_id` into Wing's `events` table; agent runs are attributed to a
  named Authentik identity, never a shared secret.

## 3. Subprocessors & cross-border transfers

The default posture is **none**. Any genuine third-party processor (e.g. an
external e-signature backend) is declared per service in the DPA register's
*"Transfers & processors"* section. As shipped, that section reads *"None —
every processing activity is fully EU-resident and self-hosted."* Operators who
add a Tier-2 app with an external dependency MUST declare it in the app's
`gdpr:` block; the apps_runner parser refuses a manifest without a complete
Article-30 block.

## 4. Retention & erasure

- **Retention horizon** is declared per service (`gdpr.retention_days` in each
  plugin) and rendered into the DPA register. `-1` = lifecycle-managed (deletion
  via DSAR); `0` = transient/not persisted.
- **Enforcement** — `roles/pazny.audit_retention` purges Wing `events` and
  Authentik events past their horizon on a Pulse schedule.
- **Right to erasure (Art. 17)** — `ansible-playbook main.yml --tags gdpr-forget
  -e forget_subject=<email>` fans the deletion out across Authentik + the
  services holding that subject's data, emits a Bone `gdpr_forget_user` audit
  event, and logs the request in Wing's `gdpr_dsar` table (`request_type=erase`)
  for inspection evidence.
- **DSAR tracking** — the `gdpr_dsar` table records every access / rectify /
  erase / portability / object request and its disposition, with the
  `gdpr_processing.id`s touched, so a CNIL-style inspection can trace each one.

## 5. Backup & recovery

Nightly encrypted backup to RustFS; restore via the `restore` playbook tag. See
[`restore-runbook.md`](restore-runbook.md). Backups inherit the at-rest disk
encryption of their target volume.

## 6. Hardening

- **Linux** — `roles/pazny.linux.hardening` applies an ANSSI-derived sysctl +
  auditd baseline; mapping to ANSSI references in [`anssi-mapping.md`](anssi-mapping.md).
- **Platform** — weak-prefix gate (SEC-16) refuses unsafe master secrets on a
  public tenant; Pulse jobs run under a command allowlist with a scrubbed child
  env (SEC-17); the telemetry callback scrubs secret values before they reach
  Wing's store (SEC-18). Full hardening log: [`RELEASE.md`](../RELEASE.md).

## 7. What the operator still owns

nOS automates the architecture; these remain the operator's duty:

1. Enable full-disk encryption (FileVault / LUKS) before processing personal data.
2. Choose a strong `global_password_prefix` (≥12 chars; the SEC-16 gate enforces this on public tenants).
3. Keep the DPA register honest — author a real `gdpr.purpose` for the services
   the register flags with † (auto-generated placeholder), and declare any
   external processor you introduce.
4. Respond to DSARs within the statutory window using the erasure tooling above.
