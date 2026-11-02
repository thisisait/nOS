# nOS host installer — EXPERIMENTAL (v0.18)

Turns a blank PC into an Ubuntu Server 24.04 LTS host with the nOS checkout in `~/nOS`.
Proven once, 2026-11-01, on a 2012 Mac mini (the Linux test host). Roadmap row:
`release-installer-usb` (next: run `./bootstrap.sh` in the installer, a Linux builder).

## What it does
1. Renders an autoinstall seed from `user-data.tmpl`: hostname, user, your ssh public keys,
   the SHA-512 hash of a password you type (never the password itself).
2. Downloads Ubuntu's official ISO and its `SHA256SUMS`, checks the **gpg signature** of the sums,
   then the ISO against them. Nothing modified is published: the ISO is remastered on your machine.
3. Puts the seed on the disk and points grub at it. The installer asks **once** ("Continue with
   autoinstall?") before it touches a disk, so a stray boot wipes nothing.
4. Writes it to an external disk you name, refusing an internal disk or one larger than `--max-gb`
   (default 600, so a backup disk is not erased by a typo); you type `ERASE`.

## Use (macOS)
```
tools/installer/build-usb.sh --host mini --user alice
```
Then: unplug every other large disk from the target (the installer takes the largest disk),
plug the network cable, boot from the stick (Mac: hold ⌥), confirm once. After the reboot:
`ssh alice@<ip>`, `cd ~/nOS && ./bootstrap.sh`, then the first converge the bootstrap prints.

`--render-only DIR` writes just the seed (no download, no disk) — what the gate uses.
