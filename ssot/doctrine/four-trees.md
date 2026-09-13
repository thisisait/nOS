# The four trees

> Doctrine, 2026-08-03. Written after one day in which the confusion between
> these four cost time five separate times, each in a different disguise.

There is no single "the code". There are **four trees**, they are routinely out
of step with each other, and almost every "why didn't my fix take effect?" is one
of them being mistaken for another.

## 1. The four

| # | tree | where | who writes it | who reads it |
|---|---|---|---|---|
| 1 | **the branch** | `origin/dev` on GitHub | pushes | CI, and a `pull` |
| 2 | **the checkout** | `/Users/pazny/projects/nOS` | the operator's `pull`; **also the nightly jobs** | `ansible-playbook`, **Bone**, Pulse |
| 3 | **the worktree** | `.claude/worktrees/<name>` | an agent session | that session, and nothing else |
| 4 | **the estate** | containers, `~/.nos/`, `~/wing/`, `/Volumes/SSD1TB/nOS/data` | a converge | the running services |

A commit **shall** change tree 1. A pull **shall** change tree 2. A converge
**shall** change tree 4. Nothing **may** propagate on its own.

## 2. The five ways this billed on one day

Each of these looked like a different bug and was the same one.

1. **The metabase fix that "didn't work".** Committed to `dev`, verified green —
   the operator re-ran the playbook and hit the identical error. The checkout was
   one commit behind. *Repo ≠ checkout.*
2. **Twenty-one commits behind.** A whole day's work sat in tree 1 while the
   blank was being planned against tree 2.
3. **Bone reports a different `head_sha` than the work being done.** Correct:
   **Bone reads tree 2**, so the weakness reader describes the operator's
   checkout, never the agent's worktree.
4. **restic: `wrong password or no key found`.** `default.config.yml` says
   `restic_repo: ""`; the operator's `config.yml` says `/Volumes/SSD1TB/nos-restic`.
   Only the default was checked. There is a fifth surface — the operator's own
   overrides — and it **shall** win.
5. **The nightly scan writes into tree 2.** `remediation-queue.json` and
   `scan-state.json` are rewritten at 02:00 by a Pulse job, so the checkout is
   dirty before anyone touches it, and a `pull --ff-only` refuses. Every time.

## 3. The rules

**R1 — Name the tree.** "It's fixed" is not a status. *Fixed in the branch*,
*pulled into the checkout* and *converged onto the estate* are three different
claims. Only the third **shall** mean a service behaves differently.

**R2 — The checkout is the only tree the estate is built from.** Ansible, Bone
and Pulse all read `/Users/pazny/projects/nOS`. A worktree **must** stay
invisible to every one of them. An agent that wants its work to reach the
estate **must** land it in tree 1 and wait for a pull.

**R3 — Before any converge, reconcile 2 with 1.** `git -C … pull --ff-only`.
When it refuses because of the scan files, the operator **shall** check
whether they differ from the incoming version before discarding: on 2026-08-03
they were byte-identical and `git checkout --` was safe; on another day they
will not be.

**R4 — `config.yml` and `credentials.yml` outrank the defaults, and are not in
git.** They are a fifth surface that no gate can see and no agent **shall**
assume. Read the *effective* value, never the default, before reasoning about
behaviour. This is the version-pin shadow rule (memory
`version-pins-default-config-shadow`) generalised: it is not only about
version pins.

**R5 — A scheduled job writing into tree 2 is a weakness, not a nuisance.** It
is the first thing `GET /api/v1/loop/weaknesses` reports, ranked HIGH — a
checkout dirty by design blocks R3 and trains the operator to discard
changes without reading them.

**R6 — Under a worktree lease, paths are immutable**
([`docs/hidden_fees/14`](../../docs/hidden_fees/14-a-long-run-cut-from-under.md)).
Adding a path is always safe. Moving or deleting one **must not** break an
in-flight reader in tree 3.

## 4. The question to ask when something "didn't take"

> **Which tree did I change, and which tree is being read?**

Five of five incidents on 2026-08-03 answer to that sentence. None of them
answered to "is the code correct".
