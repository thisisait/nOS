# macOS 27 "Golden Gate" — nOS readiness

> Research 2026-07-18 (web, sourced). Companion to `tasks/macos27-preflight.yml`
> (the loud preflight) + `docs/doctrine/virtiofs.md` + the roadmap macOS-27 epic.

## Verdict

macOS 27 **"Golden Gate"** (public beta since 2026-07-13, **GA ~September 2026**,
Apple-Silicon-only, last release with full Rosetta 2) is **unlikely to hard-break
nOS**, but carries **two real risks + several silent-change-prone unknowns**.

**Posture: do NOT upgrade the daily-driver Mac to 27 until Docker Desktop ships an
explicit "Golden Gate supported" build**, then run **one supervised `blank=true` on a
throwaway 27 environment** watching for the VirtioFS bind-mount regression class.

## Risk map

| Area | Status | Impact on nOS | Action |
|---|---|---|---|
| **Docker Desktop / VirtioFS** | ⚠️ UNVERIFIED — no Golden-Gate support declared as of DD 4.82.0 | **TOP RISK.** New OS + uncertified Docker is exactly what has surfaced nOS's VirtioFS stale-handle / `realdirpath ENOTSUP` / stale `/host_mnt` bugs before. DD min OS is now Sonoma 14; osxfs gone (VirtioFS only); Apple-Virtualization is the default VMM. | Wait for a GG-supported DD build; supervised throwaway blank; watch the `# VFS-DOCTRINE:` surfaces. |
| **TLS clampdown (27.0)** | ✅ CONFIRMED, scoped | Stricter TLS enforcement targets **Apple system/MDM processes only** — NOT Docker/curl/browser traffic. mkcert `*.<tld>` local TLS should keep working. | Keep the mkcert profile ATS-clean (TLS 1.2+/1.3, ECDHE, AES-GCM); verify browsers accept the root on 27. |
| **TCC hardening** | ✅ CONFIRMED | Apps can't read the TCC DB; cross-team container access denied by default. nOS doesn't poke TCC — but **Full Disk Access / Automation consent likely needs re-granting** after upgrade (Docker, Terminal/tmux, `osascript`/`open -a Docker`). | Post-upgrade, re-grant FDA/Automation; watch the GUI-killall + `open -a Docker` paths for a first-run consent stall. |
| **launchd / launchctl** | ✅ UNKNOWN — no 27-specific removal | Legacy `launchctl load/unload` still works (deprecated since 10.10, not pulled in 27). **This validates deferring the wholesale bootstrap/bootout rewrite.** | Low priority; migrate residual `load/unload` call sites opportunistically (standing threat), not urgent for 27. |
| **DNS resolver** | ✅ UNKNOWN — no 27-specific change | `/etc/resolver/*` + dnsmasq on 127.0.0.1:53 expected unchanged (silent-change-prone area). | On 27 beta: `scutil --dns` shows the resolver + `dig @127.0.0.1 x.<tld>` resolves. |
| **Homebrew** | ✅ CONFIRMED preliminary support | `golden_gate`/`arm64_golden_gate` bottles + prerelease API fallback already in-flight; **`/opt/homebrew` prefix unchanged** (ISA-bound, correct as-is). Rosetta handling deferred to macOS 28. | None pre-GA; expect some build-from-source during beta. |
| **Python** | ✅ UNKNOWN — no 27 removal | nOS is pyenv-pinned (3.13.13), not framework Python. The framework-python quirk is a GitHub-runner anomaly, OS-orthogonal. | Confirm `ansible.cfg` `interpreter_python` still resolves post-upgrade. |
| **Storage / misc removals** | ✅ CONFIRMED | AFP removed, Boot Camp removed, **encrypted HFS+/CoreStorage deprecated**. nOS backs up to RustFS (not AFP) on APFS. | Verify external volumes (`/Volumes/SSD1TB/`) are **APFS, not encrypted HFS+** — the gov at-rest/FileVault gate assumes APFS. |

## Prioritized pre-emptive actions

- **P0 — Docker:** gate the daily-driver upgrade on a GG-supported Docker Desktop build; supervised throwaway-27 blank; watch VirtioFS surfaces (`grep -rn 'VFS-DOCTRINE'`).
- **P1 — TCC:** re-grant FDA/Automation post-upgrade; verify `open -a Docker`/`osascript` don't stall.
- **P1 — TLS:** confirm mkcert validates on 27; keep the profile ATS-clean.
- **P2 — DNS:** `scutil --dns` + `dig @127.0.0.1` smoke on 27 beta.
- **P2 — launchd:** opportunistic `load/unload → bootstrap/bootout` migration (not urgent — 27 didn't remove them).
- **P3 — Homebrew / Python / storage:** low-risk; verify prefix, interpreter pin, APFS-not-HFS+ external volumes.

**Honest caveat:** Golden Gate is at beta 3 with thin low-level docs. The UNKNOWNs
(launchd, DNS, Python) are "no *published* 27-specific change," not "confirmed safe" —
re-verify against the final release notes at GA.

## Sources

Wikipedia (macOS Golden Gate), Michael Tsai, Eclectic Light (networking changes),
AppleInsider, Homebrew PR #22592, Docker Desktop release notes, MacRumors roundup,
Macworld, iClarified, ss64 (launchctl), vNinja (custom DNS resolvers). Full URL list
in the 2026-07-18 research transcript.
