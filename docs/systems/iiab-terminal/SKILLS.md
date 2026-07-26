# IIAB Terminal — Skills

> **No external skill surface.** This file deliberately declares no `**Trigger:**`
> actions, so it ingests as honest notes rather than invocable skills.

## No Invocable Surface

IIAB Terminal is an interactive SSH TUI, not a service with an API. It has no
daemon, no listening HTTP port, no domain, and no scriptable interface. The only
way to reach it is `ssh home@<host>`, which the `sshd_config` `ForceCommand`
routes straight into the Textual menu — an interactive screen an agent cannot
drive by reading a card alone.

Documenting a fake REST endpoint or a "run this command to do X" skill here
would be a confident-wrong answer, which is exactly the failure this corpus
removes. The single access action (`ssh home@<host>`) is recorded in
[README.md](README.md) as a plain note, not as a skill.

## Administration Is the Playbook, Not a Skill

Everything about IIAB Terminal — the kiosk user, the launcher, the
`ForceCommand` block, the `config.json` menu — is provisioned by
`roles/pazny.iiab_terminal` on an `ansible-playbook main.yml --tags iiab-terminal,ssh`
run. There is no runtime admin API to invoke; changes go through the playbook.
