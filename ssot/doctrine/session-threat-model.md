---
last_reviewed: 2026-10-04
review_every_days: 31
---
# The operator session — the attacker is the assistant

> Doctrine, 2026-10-04 (roadmap epic `operator-session-threat-model`, children
> 1 and 2). Review is monthly and is DATA: the front matter above, read by
> `tools/red-status.py`, which names this file when the date runs out.
> PR checklist: [docs/review/threat-checklist.md](../../docs/review/threat-checklist.md) §6.

## 1. The attacker

**The AI coding session itself** — Claude Code, Codex, any agent — running as
the operator's macOS user with a shell, repo write and the local services. It
does not need to be malicious. It needs to obey ONE instruction it read in a
fetched web page, a KEAP record, an agent report, a PR or issue body, a
dependency README, or tool output. Everything below assumes that has happened.

The dev→master PR review (CodeRabbit + the checklist) runs after the push has
reached the trunk, the forges and the next converge. It is too late to be the
first look. The first look is the push.

## 2. Assets

| asset | where | why it matters |
|---|---|---|
| secrets | `~/.nos/secrets.yml`, `credentials.yml`, keychain (`security`), browser stores, `~/.ssh`, forge tokens | one read, every service |
| gates | `tests/anatomy`, allow-lists, ratchets, `files/anatomy/apex/ruling.yml`, `tools/prepush-score.py` + prompt | a gate edited with its code certifies nothing |
| the trunk | `dev` → GitHub → Gitea/GitLab → converge | a commit becomes code on every organ |
| persistence surfaces | LaunchAgents, cron, shell rc, git hooks, Pulse jobs, `.claude/` settings, `CLAUDE.md`, skills | survives the session that planted it |
| the operator's attention | approval prompts, the push output | a rubber-stamped prompt is a granted capability |
| telemetry | Santa log (exec paths + args), `~/.nos/events/` | it is itself sensitive data |

## 3. Capabilities

Everything the operator's user can do: read any file that user can, write the
repo and `$HOME`, run any shell command, reach every local service with a
token on disk, open any outbound connection. NOT: root (sudo asks), and not
the files of another macOS user — which is why §5's boundary is a user.

## 4. Persistence and triggers — and the trace each leaves

| pattern | trace in a push diff | trace on the host | reader |
|---|---|---|---|
| gate weakened with its code | same range: gate loses assertions, names the changed code | — | prepush-score §5 |
| LaunchAgent / LaunchDaemon | new `.plist`, `launchctl`, `RunAtLoad` | plist in `~/Library/LaunchAgents` | undeclared-status |
| cron | `crontab`, `cron.d` | crontab entry | undeclared-status |
| shell rc | `>> ~/.zshrc` in a script | edited rc file | none (gap) |
| git hook | `core.hooksPath`, `.git/hooks` | `.git/hooks/*` (never in a diff) | none (gap) |
| Pulse job | `pulse:` block, `pulse_jobs` insert | `pulse_jobs` row | red-status / Wing |
| assistant settings / instructions | `.claude/`, `CLAUDE.md`, `AGENTS.md`, skills, agent prompts | `~/.claude/` (never in a diff) | none (gap) |
| dormant trigger | condition on a date literal, host, user, env, file existence | nothing until it fires | prepush-score (heuristic) |
| obfuscation | long base64, decode-and-run, `eval` | — | prepush-score |
| exfiltration | new URL host, `/dev/tcp`, `nc`, new git remote | outbound connection (no egress log) | none on the host (gap) |
| secret read | `.nos/secrets`, `security find-*`, browser store paths | — | prepush-score; Santa sees `security` exec |

## 5. The ceiling — what a push-time check cannot see

**Same-user code can rewrite any same-user check.** The scorer, its prompt,
its JSONL record, `tools/nos-push`, `red-status`, git hooks: a session running
as the operator can edit each of them, and can do it outside a commit. The
SHA-256 the scorer prints is a tripwire for the operator's eye, not a lock.

Invisible to any diff: what never enters a commit — `~/.claude/`, a plist
written straight to `~/Library/LaunchAgents`, a keychain read in the session,
a `curl` the session ran, a `.git/hooks` file. Those are host traces (§4
readers) or nothing.

The hard boundary is **the session under a separate macOS user** (epic child 3,
`pazny.mac.agent_user`, uid 480): a user that cannot read `~/.nos` cannot leak
it, whatever it was told. Until the operator's own interactive session runs
that way, everything in §6 is detection, never prevention.

## 6. The push-time decision model (child 2)

`tools/nos-push` runs `tools/prepush-score.py` BEFORE `git push`:

1. **Deterministic signals first**, from the exact push range (HEAD commits no
   `<remote>/*` ref has), each with `file:line`, never the line itself.
2. **A small local model** (Ollama, keep_alive 0, no cloud) reads the signals
   plus a redacted, bounded excerpt and returns per-aspect scores 0–100 in
   strict JSON. Anything else is `UNAVAILABLE` — never a number.
3. Aspects are the checklist sections 1–6. Output: bar chart, evidence, both
   hashes; "checker changed in this push" is the top signal.
4. One JSONL line per run in `~/.nos/events/prepush-scores.jsonl` — scores,
   labels, hashes, range. No diff text, no reasons, no secrets.

**Advisory.** It prints and never blocks; `nos-push --strict` refuses at 70.
These are **scores, not probabilities**: uncalibrated until the JSONL has
enough runs to compare against what the review later found.

## 7. The monthly review

Re-read §4 against what shipped; compare a month of `prepush-scores.jsonl`
with what the PR review and incidents found (false reds, misses); retune
weights; then move `last_reviewed`. A review that changes nothing still moves
the date — it is a dated act, and the date is what the reader checks.
