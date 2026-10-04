# Threat checklist for pull requests

What the workload allow-list does not catch, checked on every PR. Advisory:
the reviewer comments and summarises, it never approves, blocks or merges.
Engine: CodeRabbit (`.coderabbit.yaml` reads this file). Any engine reads the same text.

For each section, name the file and line, say what changed, and say whether the
change is declared somewhere a reader checks (a gate, a manifest row, a plugin).

## 1. What runs got wider
- New executables, Pulse job commands, launchd/systemd units, cron entries.
- New compose services, published ports, `docker.sock` mounts, `privileged`,
  `network_mode: host`, host bind mounts outside the service's data dir.
- An install flag defaulting to true, or a service auto-enabled by another flag.

## 2. Supply chain
- New or changed images; an image tag without a `@sha256` digest.
- `--build` from a `*_src_dir` (local source becomes a running image).
- New package dependencies (composer, npm, pip, brew, cargo) and their install
  scripts; `curl … | sh` or `bash <(curl …)` anywhere.

## 3. Secrets and credentials
- Reads of `~/.nos/secrets.yml` or Infisical outside the existing resolvers.
- A secret printed, logged, written into a rendered file outside 0600, or put in a URL.
- Environment variables that override a binary path (`INFISICAL_BIN`-class).
- Tokens with write scope handed to agents or Pulse jobs.

## 4. Agent power
- `bypassPermissions`, a widened `--allowedTools`/`--add-dir`, a new MCP tool.
- New Wing or Bone write endpoints; any path letting an agent insert a
  `pulse_jobs` row or change an allow-list.

## 5. Self-review laundering
- An allow-list, gate, ratchet or expected value changed in the same PR as the
  code that needs it. A gate that passes because it was edited is not a gate:
  ask for the gate to be shown red against the old code first.
- A test weakened, skipped or deleted next to the change it would have caught.
