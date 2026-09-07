---
title: Admin — backup and restore
section: admin
order: 4
summary: restic to the local backup disk every night, a restore drill every morning, Backrest to browse — and the exact order to rebuild the box.
---

## The shape

| Piece | What |
|---|---|
| repository | `/srv/backup/restic` on the external disk (ext4, label `nos-backup`, mounted from fstab with `nofail`) |
| writer | `nos-dgx-backup.timer` → `/srv/nos-dgx/backup/nos-dgx-backup.sh`, 03:00 nightly, as root |
| reader | `nos-dgx-backup-verify.timer` → `nos-dgx-backup-verify.sh`, 04:30 daily: restores the KEAP database from the latest snapshot into a scratch dir, counts the roadmap rows, compares with the live table, writes `/var/lib/nos-dgx/backup/last.json` |
| UI | Backrest at `https://__HOST__:8446/` (admin only: PAM, group `nos-maintainers`) — browse snapshots, restore files; it schedules nothing |
| retention | 8 weekly + 7 daily; `prune` and a 10 % `check` every Sunday |
| key | `/etc/nos/restic.env` (root 0600) and a copy in `/root/nos-dgx-restic.password`. **Put it in your password manager.** Without it the disk is noise. |

**The backup never says "OK" about itself.** The verdict is the verifier's:

```
cat /var/lib/nos-dgx/backup/last.json
```

`OK` = the latest snapshot is under 26 h old and a restored KEAP database has
roadmap rows; `STALE` = the backup did not run; `BROKEN` = restore failed;
`UNKNOWN` = disk absent or repository unreadable. If the disk is not mounted
the backup **refuses** (exit 75) instead of filling the root filesystem.

## What is in a snapshot

`/etc/nos` (tokens, CA, Hub config), online SQLite snapshots of KEAP, Chat,
n8n and the Hub (`stage/*.db`, WAL-safe, taken without stopping anything),
KEAP's data dir, the Chat and n8n volumes, the seed repo, `/home` of every
user **except** their rootless Docker store, caches, venvs and `node_modules`,
TLS leaf + user-slice drop-in, and inventories: `ollama-models.txt`,
`docker-images.txt`, `dpkg-selections.txt`, the account files
(`passwd/group/shadow/subuid/subgid`), the linger list. Models and images are
lists, never blobs — they are re-pulled.

## Day-to-day

```
sudo systemctl list-timers 'nos-dgx-*'          # next runs
sudo tail -20 /var/lib/nos-dgx/backup/backup.log
sudo systemctl start nos-dgx-backup.service     # run one now
sudo systemctl start nos-dgx-backup-verify.service && cat /var/lib/nos-dgx/backup/last.json
sudo -E bash -c '. /etc/nos/restic.env; export RESTIC_REPOSITORY RESTIC_PASSWORD; restic snapshots'
```

Backrest (8446) shows the same repository; use it to browse and restore a file
or a user's directory to a chosen path. Do **not** add plans there while the
timer is active — one writer per repository. If you prefer Backrest as the
scheduler: `sudo systemctl disable --now nos-dgx-backup.timer` first, keep the
verifier.

## Restore one thing

```
sudo -E bash -c '. /etc/nos/restic.env; export RESTIC_REPOSITORY RESTIC_PASSWORD
  restic restore latest --target /tmp/r --include /home/svp2bj/projects/foo'   # a directory
  restic restore latest --target /tmp/r --include /var/lib/nos-dgx/backup/stage/keap.db'   # KEAP db
```

To put a database back: stop its container, copy the restored `.db` over the
live file (drop `-wal`/`-shm`), start it. KEAP: `/srv/nos-dgx/keap/data/keap.db`;
Chat: `/var/lib/docker/volumes/open-webui/_data/webui.db`; n8n:
`/var/lib/docker/volumes/iiab_n8n_data/_data/database.sqlite`.

## Rebuild the box from nothing (the order matters)

1. Ubuntu 24.04 + Docker CE; clone nOS; **do not run the recipe yet**.
2. Attach the backup disk; `mkdir -p /srv/backup && mount -L nos-backup /srv/backup`.
3. Restore `/etc/nos` **first** (the recipe generates new tokens only when it is
   absent) and the account files from `stage/etc/` if you want the same
   logins and uids: `passwd group shadow gshadow subuid subgid`.
4. Run the recipe once: nginx, KEAP image, Hub, Ollama, users' shelves come up
   on the restored tokens.
5. Stop the stack, restore `stage/keap.db` → `/srv/nos-dgx/keap/data/keap.db`,
   `stage/webui.db` and the Chat volume, `stage/n8n.db` and the n8n volume,
   `/home`, `/srv/nos-seed.git`; start the stack.
6. `ollama pull` each tag in `stage/ollama-models.txt`.
7. `nos dtt status` shows the roadmap; `last.json` goes `OK` the next morning.

## Changing the disk

Format the new one with label `nos-backup` (`mkfs.ext4 -L nos-backup /dev/sdX1`),
run the recipe (it writes the fstab line and `restic init`s an empty
repository), then copy or re-seed. Two disks in rotation = two repositories;
restic does not sync them, so run one full backup on each.
