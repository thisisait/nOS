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
| **At rest (backups)** | Every nightly dump is **AES-256-CBC / pbkdf2 client-side encrypted before upload** to RustFS (`backup_encryption_enabled`, default on); object storage never holds cleartext personal data. | Playbook-managed; `backup_encryption_passphrase` custody is the operator's (lose it → backups unrecoverable). |
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
- **Enforcement** — retention purge is **operator-initiated, not yet
  scheduled**: `ansible-playbook main.yml --tags audit-retention -e
  retention_confirm=true` runs `bin/purge-events.php` to delete Wing `events`
  older than `wing_audit_retention_days`. It is dry-run by default and today
  covers the Wing `events` store only; automated, application-store-wide
  retention enforcement is tracked in [`roadmap-2026q2.md`](roadmap-2026q2.md).
- **Right to erasure (Art. 17)** — `ansible-playbook main.yml --tags gdpr-forget
  -e forget_subject=<email>` fans the deletion out across Authentik + the
  services holding that subject's data, emits a Bone `gdpr_forget_user` audit
  event, and logs the request in Wing's `gdpr_dsar` table (`request_type=erase`)
  for inspection evidence.
- **Right of access (Art. 15)** — `ansible-playbook main.yml --tags gdpr-export
  -e export_subject=<email>` assembles a per-subject access bundle. **Read-only
  and dry-run by default** (prints the plan, writes nothing); add `-e
  export_confirm=true` to write the bundle to `~/.nos/dsar-exports/<subject>-<date>/`
  (dir `0700`, files `0600`). Authentik auto-captures the single exact-email-match
  user object; every other in-scope store is `method:manual` (the run prints +
  stubs the exact export step). Logs a `gdpr_dsar` row with **`request_type=access`**
  — the universally-valid right. **Art. 20 portability** is recorded only for the
  consent/contract subset (`portability_eligible` in `state/gdpr-export-map.yml`:
  erpnext, gitea, vaultwarden); the other in-scope services run on legitimate
  interests, for which portability does not apply. Audited map:
  `state/gdpr-export-map.yml`.
- **DSAR tracking** — the `gdpr_dsar` table records every access / rectify /
  erase / portability / object request and its disposition, with the
  `gdpr_processing.id`s touched, so a CNIL-style inspection can trace each one.

## 5. Backup & recovery

Nightly backup to RustFS, **AES-256-CBC / pbkdf2 client-side encrypted before
upload** (`backup_encryption_enabled`, default on) so personal data never lands
in object storage as cleartext. Restore decrypts transparently with the same
`backup_encryption_passphrase` (`tasks/restore.yml` auto-detects the `.enc`
suffix; legacy plaintext objects still restore). **Keep that passphrase under
the same custody as `global_password_prefix` — without it, encrypted backups are
unrecoverable.** Restore via the `restore` playbook tag; see
[`restore-runbook.md`](restore-runbook.md). Host-disk at-rest FDE
(FileVault / LUKS) remains operator-provisioned (see §1).

- **DSAR access bundles are a NEW unencrypted personal-data store outside the
  backup-encryption guarantee.** `~/.nos/dsar-exports/<subject>-<date>/` holds a
  data subject's personal data in cleartext (`0700`/`0600`, no auto-encrypt, no
  auto-expiry). **Operator action:** deliver the bundle over a secure channel,
  then delete the directory; and confirm `~/.nos/` is not in the nightly RustFS
  backup scope, or these bundles will land in object storage as a fresh
  personal-data copy. Tracked as an operator decision, not an automated control.

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
