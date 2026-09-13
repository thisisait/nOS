# VirtioFS Doctrine

> Canonical decisions. A major macOS jump (26 → 27) can tighten Docker Desktop's
> bind-mount semantics; this file exists so that tightening is DETECTABLE, not silent.
> Preflight: [`tasks/macos27-preflight.yml`](../../tasks/macos27-preflight.yml).

## 1. Class

Docker Desktop on macOS bind-mounts host paths into a Linux VM over **VirtioFS**.
VirtioFS is not a local FS. Socket, lock-file, mmap, and mount-identity
semantics have bitten nOS; a new macOS release may re-open them. Linux has no
VM/propagation layer. This class of bug is macOS-Docker-Desktop only.

## 2. Off the bind

These shall not sit on a VirtioFS bind:

1. **Unix sockets** — `File.realdirpath()` on a socket over VirtioFS can return
   `Errno::ENOTSUP` and crash-loop the process (gitlab puma → 502). The sockets
   dir shall live on a `tmpfs:` (ephemeral is the correct home anyway).
2. **Lock-files / scratch state** — stale-handle carry-over across a remount
   leaves a dead lock the container cannot clear (loki tsdb-shipper scratch).
   Clean it at provisioning or move it off the bind.
3. **Memory-mapped DBs** — mmap over a network-ish FS is where silent
   corruption and `ENOTSUP`/`EINVAL` live. Use a **named volume** (VM-native),
   not a bind.

Sockets, lock-files, and mmap'd DBs shall live on a `tmpfs:` or a named volume.
A bind may hold durable, plainly-read/written data only.

## 3. Marker

Every VirtioFS workaround must carry `# VFS-DOCTRINE:` naming the surface and
the symptom it guards. `grep -rn "VFS-DOCTRINE"` must list the full inventory
of known-fragile spots.

## 4. Known workarounds

Cite when adding one:

- **gitlab puma sockets → tmpfs** — [`roles/pazny.gitlab/templates/compose.yml.j2`](../../roles/pazny.gitlab/templates/compose.yml.j2)
  (`tmpfs: /var/opt/gitlab/gitlab-rails/sockets`), fixes `realdirpath ENOTSUP`
  crash-loop.
- **loki scratch stale-dir clean** — [`tasks/stacks/core-up.yml`](../../tasks/stacks/core-up.yml)
  ("Clean stale scratch dir (macOS VirtioFS workaround)", `.../tsdb-shipper-active/scratch`).
- **external-SSD stale `/host_mnt` remount** — [`tasks/stacks/docker-external-mount-preflight.yml`](../../tasks/stacks/docker-external-mount-preflight.yml)
  (probe + self-heal when `nos_data_root` on an external `/Volumes` disk is
  remounted after Docker Desktop started).

## 5. Tightening

A new macOS major above the tested ceiling is a WATCH signal — the macOS 27
preflight warns (non-fatal) and points here. When a new VirtioFS regression
is found, the fix shall move the surface off the bind AND add a
`# VFS-DOCTRINE:` marker plus a row in §4. A silent patch is refused.
