# VirtioFS Doctrine

> Canonical decisions. A major macOS jump (26 → 27) can tighten Docker Desktop's
> bind-mount semantics; this file exists so that tightening is DETECTABLE, not silent.
> Preflight: [`tasks/macos27-preflight.yml`](../../tasks/macos27-preflight.yml).

**The class risk.** Docker Desktop on macOS runs Linux containers in a VM and
bind-mounts host paths into it over **VirtioFS**. VirtioFS is not a real local FS —
its semantics for sockets, lock-files, memory-mapped files, and mount identity
have bitten nOS repeatedly, and each new macOS release can re-open them. Linux has
no VM/propagation layer (binds hit the host FS directly), so this is a
macOS-Docker-Desktop-only class of bug.

**The rule — never put these on a VirtioFS bind:**

1. **Unix sockets** — `File.realdirpath()` on a socket over VirtioFS can return
   `Errno::ENOTSUP` and crash-loop the process (gitlab puma → 502). Put the
   sockets dir on a `tmpfs:` (ephemeral is the correct home anyway).
2. **Lock-files / scratch state** — stale-handle carry-over across a remount
   leaves a dead lock the container can't clear (loki tsdb-shipper scratch).
   Clean it at provisioning or move it off the bind.
3. **Memory-mapped DBs** — mmap over a network-ish FS is where silent corruption
   and `ENOTSUP`/`EINVAL` live. Use a **named volume** (VM-native), not a bind.

Sockets / lock-files / mmap'd DBs belong on a `tmpfs:` or a **named volume** — the
bind is for durable, plainly-read/written data only.

**Every VirtioFS workaround carries a greppable marker.** So a macOS-27
bind-semantics change is diagnosable in one `grep`, every workaround comments with
`# VFS-DOCTRINE:` (naming the surface + the symptom it guards). `grep -rn "VFS-DOCTRINE"`
must list the full inventory of known-fragile spots.

**Known workarounds in-tree (cite when adding one):**

- **gitlab puma sockets → tmpfs** — [`roles/pazny.gitlab/templates/compose.yml.j2`](../../roles/pazny.gitlab/templates/compose.yml.j2)
  (`tmpfs: /var/opt/gitlab/gitlab-rails/sockets`), fixes `realdirpath ENOTSUP`
  crash-loop.
- **loki scratch stale-dir clean** — [`tasks/stacks/core-up.yml`](../../tasks/stacks/core-up.yml)
  ("Clean stale scratch dir (macOS VirtioFS workaround)", `.../tsdb-shipper-active/scratch`).
- **external-SSD stale `/host_mnt` remount** — [`tasks/stacks/docker-external-mount-preflight.yml`](../../tasks/stacks/docker-external-mount-preflight.yml)
  (probe + self-heal when `nos_data_root` on an external `/Volumes` disk is
  remounted after Docker Desktop started).

**Make the tightening loud.** A new macOS major above the tested ceiling is a
WATCH signal — the macOS 27 preflight warns (non-fatal) and points here. When a
new VirtioFS regression is found, fix it off-the-bind AND add a `# VFS-DOCTRINE:`
marker + a row above; never patch it silently.
