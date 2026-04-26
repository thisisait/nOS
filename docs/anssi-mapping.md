# ANSSI hardening rule mapping — `pazny.linux.hardening`

This doc maps the rules implemented by `roles/pazny.linux.hardening/` to their references in:

- ANSSI **NT-028** *Recommandations de configuration d'un système GNU/Linux* (v2 - January 2019, the public master reference)
- **cloud-gouv/securix** (the French government's NixOS hardening framework — its rule set is the practical translation of NT-028 to a deployable artifact, and what we mirror in concept on Debian/Ubuntu)
- **CIS Benchmarks** (Ubuntu 24.04 LTS) for cross-reference where ANSSI rules don't exist

We are **not** claiming ANSSI certification. nOS is a single-tenant home-lab + SMB target; the role implements the *spirit* of the recommendations at a level a small operator can audit and roll back. Regulated production deployments need an auditor + the full NT-028 rule set, plus AIDE / SELinux MAC mode / immutable auditd.

Track D scope (Q2 2026): ufw + fail2ban + sysctl + auditd + AppArmor + chrony + sshd + unattended-upgrades. Out of scope and tracked for future iterations: AIDE, SELinux, encrypted root partitions, USBGuard, kernel module signing.

---

## Rule mapping table

Each row links a single configuration item to (1) the file in this role that applies it, (2) the upstream ANSSI / CIS rule, and (3) why we chose the specific value.

| nOS rule | Implemented by | ANSSI / CIS reference | Notes |
|---|---|---|---|
| `ufw default deny incoming, allow outgoing` | `tasks/ufw.yml` | NT-028 §R23 / CIS 3.5.1.1 | Plus explicit allow for SSH, HTTP, HTTPS, Tailscale |
| `fail2ban — sshd jail (4 retries, 2h ban)` | `tasks/fail2ban.yml` | NT-028 §R52 / CIS 4.4 | ANSSI default is 4 retries / human users |
| `fail2ban — nginx-http-auth jail` | `tasks/fail2ban.yml` | securix `services.fail2ban.jails.nginx` | Brute-force throttle for proxy-auth-protected vhosts |
| `net.ipv4.conf.*.rp_filter = 1` | `tasks/sysctl.yml` | NT-028 §R30 / CIS 3.3.7 | Anti-spoofing |
| `net.ipv4.tcp_syncookies = 1` | `tasks/sysctl.yml` | NT-028 §R31 / CIS 3.3.8 | SYN flood mitigation |
| `net.ipv4.icmp_echo_ignore_broadcasts = 1` | `tasks/sysctl.yml` | NT-028 §R32 / CIS 3.3.5 | Smurf attack mitigation |
| `net.ipv4.conf.*.accept_source_route = 0` | `tasks/sysctl.yml` | NT-028 §R28 / CIS 3.3.1 | Source-routed packet rejection |
| `net.ipv4.conf.*.accept_redirects = 0` | `tasks/sysctl.yml` | NT-028 §R29 / CIS 3.3.2 | ICMP redirect rejection |
| `kernel.randomize_va_space = 2` | `tasks/sysctl.yml` | NT-028 §R7 / CIS 1.5.3 | ASLR full |
| `kernel.kptr_restrict = 2` | `tasks/sysctl.yml` | NT-028 §R8 | Hide kernel pointers from userland |
| `kernel.dmesg_restrict = 1` | `tasks/sysctl.yml` | NT-028 §R9 | Restrict `dmesg` to root |
| `fs.protected_hardlinks = 1`, `fs.protected_symlinks = 1` | `tasks/sysctl.yml` | NT-028 §R12 / CIS 1.6.1 | Symlink/hardlink TOCTOU mitigations |
| `fs.suid_dumpable = 0` | `tasks/sysctl.yml` | NT-028 §R13 / CIS 1.5.1 | No core dumps for setuid binaries |
| `auditd — log identity changes (passwd/group/shadow)` | `tasks/auditd.yml` | NT-028 §R55 / CIS 4.1.3.7 | `-w /etc/passwd -p wa -k identity` etc. |
| `auditd — log sudoers + sudo invocations` | `tasks/auditd.yml` | NT-028 §R55 / CIS 4.1.3.4 | Privilege escalation trail |
| `auditd — log time changes` | `tasks/auditd.yml` | NT-028 §R56 / CIS 4.1.3.16 | Crucial for token validation timeline |
| `auditd — log module load/unload` | `tasks/auditd.yml` | NT-028 §R57 / CIS 4.1.3.20 | Detects rootkit-class malware |
| `auditd buffer 8192` | `tasks/auditd.yml` | NT-028 §R54 | Trade-off vs RAM; default for home labs |
| `AppArmor enabled + apparmor-profiles` | `tasks/apparmor.yml` | securix `security.apparmor.enable = true` | Debian's MAC stack (RHEL would use SELinux) |
| `chrony installed + enabled` | `tasks/chrony.yml` | NT-028 §R44 / CIS 2.2.1.2 | Time sync for token validity + audit logs |
| `sshd — no password auth, no root login, MaxAuthTries=3` | `tasks/ssh.yml` | NT-028 §R69-R72 / CIS 5.2 | ANSSI doesn't formalise MaxAuthTries; CIS recommends ≤4 |
| `sshd — X11Forwarding no, AllowAgentForwarding no` | `tasks/ssh.yml` | NT-028 §R74 / CIS 5.2.4 | Reduce lateral-movement surface |
| `sshd — ClientAliveInterval 300, ClientAliveCountMax 2` | `tasks/ssh.yml` | securix sshd defaults | 10-min idle timeout |
| `unattended-upgrades — security pocket only` | `tasks/unattended.yml` | NT-028 §R3 / CIS 1.9 | Keep up with CVE patches without surprising operator with major-version bumps |

## Items intentionally NOT included

| Item | Why not in v1 | Tracking |
|---|---|---|
| AIDE (file integrity monitor) | Noisy without a separate quarantine host to compare baselines; for v1 we rely on auditd + fail2ban | Track D phase 2 |
| SELinux | RHEL-only; AppArmor is Debian's primary MAC | RHEL sibling role tracked |
| `kernel.unprivileged_userns_clone = 0` | Breaks rootless Docker, Podman, snap | Conditional toggle, future |
| LUKS root encryption | Set at OS install time, not by ansible | Documented in `docs/linux-port.md` |
| USBGuard | Single-user lab, low value vs setup pain | Future, with USB allow-list ergonomics |
| Kernel module signing enforcement | Requires distro kernel + dkms work | Track ANSSI BP-040 §R6 follow-up |
| `kernel.yama.ptrace_scope = 1` | Conflicts with debuggers Wing operators may need | Opt-in flag in v2 |

## Operator overrides

To **disable a single subsystem** (e.g. you want your own iptables rules instead of ufw):

```yaml
# config.yml
hardening_ufw: false
```

To **switch auditd to immutable mode** for production:

```yaml
hardening_auditd_immutable: true   # requires reboot for rule changes after this
```

To **disable hardening wholesale**:

```yaml
install_hardening: false
```

## Verification

After a successful playbook run:

```bash
# 1. ufw status
sudo ufw status verbose
# expect: Status: active, Default: deny (incoming), allow (outgoing)

# 2. fail2ban jails
sudo fail2ban-client status
# expect: sshd, nginx-http-auth listed as jailed

# 3. sysctl
sysctl net.ipv4.tcp_syncookies kernel.randomize_va_space fs.protected_symlinks
# expect: 1, 2, 1

# 4. auditd
sudo auditctl -l | head -10
# expect: rules from /etc/audit/rules.d/99-nos.rules

# 5. AppArmor
sudo aa-status
# expect: N profiles loaded, M in enforce mode

# 6. chrony
chronyc tracking
# expect: Reference ID, Stratum, Last offset reported

# 7. sshd config
sudo sshd -T | grep -E '^(passwordauthentication|permitrootlogin|maxauthtries)'
# expect: no, no, 3

# 8. unattended-upgrades dry-run
sudo unattended-upgrade --dry-run -d 2>&1 | tail -20
# expect: "All upgrades installed" or list of what would be upgraded
```

## References

- **ANSSI NT-028 v2** (Jan 2019) — *Recommandations de configuration d'un système GNU/Linux*. The 84-rule master document. Public PDF on [cyber.gouv.fr](https://cyber.gouv.fr/publications).
- **cloud-gouv/securix** — French government's NixOS-based hardened reference distribution. Repository: https://github.com/cloud-gouv/securix. Useful as a sanity check for "what does the French gov actually run".
- **CIS Ubuntu 24.04 LTS Benchmark** — practical version-specific control list. Used as the implementation guide where NT-028 rules don't have an exact distro mapping.
- **DISA STIG Ubuntu 22.04** — US DoD equivalent; cross-referenced where it has a tighter rule than NT-028 (e.g. SSH MaxAuthTries).
