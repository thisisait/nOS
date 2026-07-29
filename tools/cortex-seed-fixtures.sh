#!/usr/bin/env bash
# =============================================================================
# cortex-seed-fixtures.sh — give the corpus diff something to measure
#
# WHY THIS EXISTS
# ---------------
# `cortex-corpus-diff` compares KEAP's corpus against the organ's. Its first
# honest night (2026-07-28) passed all six clauses and still closed with:
#
#     This run does not show that ingestion is correct. It shows that two
#     near-empty corpora are equally near-empty.
#
# `realUserDocs: 2` against a disclosure floor of 25 — and both of those two are
# binaries (a PNG and a PDF), so NO user-side text has ever exercised body
# hashing, BODY_CAP, or embedding. This script seeds the well-behaved 80 %:
# plain Markdown, ASCII paths, bodies under the cap, one uid, one tenant.
#
# It deliberately does NOT exercise the nine behaviours the harness lists as
# unmeasured (prune, move/rename, multi-user attribution, visibility flip, the
# 20 000-file cap, EACCES truncation, a second tenant, bodies over BODY_CAP,
# non-ASCII paths). Those are a DELIBERATE streak restart, not a side effect —
# run them after the three-night clock finishes. See
# docs/plans/cortex-s3-s4-workflow-set.md §1.
#
# WHY YOU RUN IT, NOT AN AGENT
# ----------------------------
# The tenant tree lives on an external volume. macOS TCC grants that path to
# Terminal.app and to Docker Desktop, but not to a background agent process —
# an agent gets EPERM before it gets a permission error. Files here should also
# be owned by uid 501, which is what a user creating them produces.
#
# USAGE
#   tools/cortex-seed-fixtures.sh                 # seed + kick fs-sync
#   tools/cortex-seed-fixtures.sh --check         # seed, then run the diff
#                                                 #   with --no-ledger (the
#                                                 #   night count is untouched)
#   tools/cortex-seed-fixtures.sh --purge         # remove exactly what it wrote
#
# Everything lands under <users>/<uid>/documents/cortex-fixtures/ and --purge
# removes that directory and nothing else.
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DATA_ROOT="${NOS_DATA_ROOT:-/Volumes/SSD1TB/nOS/data}"
TENANT="${NOS_TENANT_SLUG:-pazny}"
UID_DIR="${CORTEX_FIXTURE_UID:-akadmin}"
KEAP_URL="${KEAP_API_URL:-http://127.0.0.1:8091}"

USERS_ROOT="${DATA_ROOT}/tenants/${TENANT}/users"
TARGET="${USERS_ROOT}/${UID_DIR}/documents/cortex-fixtures"

WING_DB="${WING_DB:-$HOME/wing/app/data/wing.db}"

# ── Job env comes from the rendered Pulse catalog, not from your shell ───────
# Every feeder needs tokens (and keap-consolidate needs the MariaDB root
# password besides). Ansible pre-renders those into wing.db's `pulse_jobs`
# rows, which is what the nightly actually executes with — so reading them
# back is the only way a manual run measures the SAME conditions as a night
# rather than an approximation of one. Exporting them by hand invites a
# diagnostic that fails on auth and reads as a corpus disagreement.
job_env () {
  python3 - "$WING_DB" "$1" <<'PY'
import json, sqlite3, sys, shlex
db, job = sys.argv[1], sys.argv[2]
try:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = c.execute(
        "select env_json from pulse_jobs where job_name=? and removed_at is null", (job,)
    ).fetchone()
except sqlite3.Error as e:
    print(f"# wing.db unreadable: {e}", file=sys.stderr)
    sys.exit(1)
if not row:
    print(f"# no pulse_jobs row for {job}", file=sys.stderr)
    sys.exit(1)
for k, v in sorted(json.loads(row[0] or "{}").items()):
    print(f"export {k}={shlex.quote(str(v))}")
PY
}

# Best-effort: the seed step only needs KEAP's RW token to kick fs-sync.
if [ -z "${KEAP_AGENT_TOKEN_RW:-}" ]; then
  eval "$(job_env keap-embed-sync 2>/dev/null | grep '^export KEAP_AGENT_TOKEN_RW=' || true)"
fi

MODE="seed"
case "${1:-}" in
  --purge) MODE="purge" ;;
  --check) MODE="check" ;;
  "") ;;
  *) echo "usage: $(basename "$0") [--check|--purge]" >&2; exit 2 ;;
esac

# ── Guards ───────────────────────────────────────────────────────────────────
# The target must sit inside a tenant's user tree. Without this, a mistyped
# NOS_DATA_ROOT would scatter fixtures across an unrelated directory — and
# --purge would then delete an unrelated directory.
case "$TARGET" in
  */tenants/*/users/*/documents/cortex-fixtures) ;;
  *) echo "refusing: '$TARGET' is not <data>/tenants/<t>/users/<uid>/documents/cortex-fixtures" >&2; exit 1 ;;
esac

if [ ! -d "$USERS_ROOT" ]; then
  echo "refusing: users root '$USERS_ROOT' does not exist (external volume not mounted?)" >&2
  exit 1
fi

if [ "$MODE" = "purge" ]; then
  if [ -d "$TARGET" ]; then
    n=$(find "$TARGET" -type f | wc -l | tr -d ' ')
    rm -rf "$TARGET"
    echo "purged $n file(s) from $TARGET"
  else
    echo "nothing to purge — $TARGET does not exist"
  fi
  curl -fsS -X POST -H "Authorization: Bearer ${KEAP_AGENT_TOKEN_RW:-}" \
    "${KEAP_URL}/agent/v1/fs/sync" -o /dev/null 2>/dev/null \
    && echo "fs-sync kicked (removals propagate)" \
    || echo "NOTE: could not kick fs-sync — set KEAP_AGENT_TOKEN_RW, or wait for the 300 s interval"
  exit 0
fi

# ── Seed ─────────────────────────────────────────────────────────────────────
# One note per call: doc <relative-path> <<'EOF' … EOF
# Frontmatter carries `fixture: cortex-seed` so a fixture is always identifiable
# in the corpus, and prose stays short — a real note is short, and 26 near-
# identical documents would be a weak test of an embedding index.
doc () {
  local rel="$1"
  local path="${TARGET}/${rel}"
  mkdir -p "$(dirname "$path")"
  cat > "$path"
}

mkdir -p "$TARGET"

doc "meeting-notes/2026-07-06-supplier-review.md" <<'EOF'
---
title: Supplier review — Q3 planning
date: 2026-07-06
fixture: cortex-seed
---

Went through the three print suppliers on the shortlist. Example Print quoted
14-day terms and can hold stock for us; the other two want payment on delivery,
which we can absorb for one-off jobs but not for the recurring monthly run.

Decision: keep Example Print as primary for recurring work. Revisit in October
when the current price list expires. Nobody has checked whether their arm64
proofing workflow matters to us — it does not, we send PDFs.
EOF

doc "meeting-notes/2026-07-09-quarterly-numbers.md" <<'EOF'
---
title: Quarterly numbers walkthrough
date: 2026-07-09
fixture: cortex-seed
---

Revenue tracked slightly ahead of plan, driven almost entirely by two large
invoices that landed early rather than by new business. Treating that as timing,
not growth.

Cost side: the biggest single line is still infrastructure we do not use at peak.
Action: measure actual concurrent load for four weeks before renewing anything.
EOF

doc "meeting-notes/2026-07-14-onboarding-retro.md" <<'EOF'
---
title: Onboarding retro
date: 2026-07-14
fixture: cortex-seed
---

Two people joined in June. Both said the same thing independently: the written
docs were good, but nothing told them which of the ~50 services they actually
needed on day one. They each spent most of the first week discovering that the
answer was four.

Action: a one-page "day one" list. Not more documentation — less.
EOF

doc "meeting-notes/2026-07-21-incident-review.md" <<'EOF'
---
title: Incident review — helpdesk outage
date: 2026-07-21
fixture: cortex-seed
---

Helpdesk was unreachable for roughly 40 minutes. Root cause was not the service
itself but a dependency restarting underneath it during a routine converge.

The uncomfortable part: nobody noticed until a customer wrote in. The monitor
existed and was green, because it checked the port rather than a real request.
Action: make the check fetch a page that requires the database.
EOF

doc "finance/invoicing-rules.md" <<'EOF'
---
title: Invoicing rules of thumb
fixture: cortex-seed
---

Invoice on completion for one-off work, monthly in arrears for retainers. Net 14
by default; net 30 only where the counterparty's own process genuinely cannot go
faster (public sector mostly), and net 60 never without a written reason.

Always put the purchase-order reference in the invoice header when the customer
uses one. Half of our late payments have been an invoice sitting in someone's
inbox because it could not be matched automatically.
EOF

doc "finance/vat-notes.md" <<'EOF'
---
title: VAT notes
fixture: cortex-seed
---

Domestic supplies at the standard rate. Cross-border B2B within the EU is reverse
charge — the customer's VAT ID must be validated at the time of invoicing, not at
the time of the quote, because IDs do get deregistered in between.

Keep the validation response. "We checked" is not a defence; the timestamped
response is.
EOF

doc "finance/expense-categories.md" <<'EOF'
---
title: Expense categories we actually use
fixture: cortex-seed
---

Hardware, hosting, software subscriptions, travel, professional services,
office. Everything else goes to "other" and gets reviewed quarterly — if a line
in "other" appears three quarters running it earns its own category.

Hosting and software subscriptions are deliberately separate: one scales with
usage and the other does not, and merging them hides which is which.
EOF

doc "finance/payment-terms-policy.md" <<'EOF'
---
title: Payment terms policy
fixture: cortex-seed
---

We ask for net 14 and we pay net 14. Asking suppliers for terms we do not offer
has never once been worth the goodwill it costs.

Exception: a supplier who offers a discount for early settlement gets settled
early, provided the discount beats what the cash would otherwise do — which,
at current rates, it usually does.
EOF

doc "ops/backup-expectations.md" <<'EOF'
---
title: What the backups actually promise
fixture: cortex-seed
---

Nightly, encrypted, off the primary volume. That is the promise. What it is NOT:
continuous, and not a substitute for versioning inside the applications.

A restore has been rehearsed for the databases. It has not been rehearsed for
the object store, and until it has, the honest recovery estimate for that tier
is "unknown", not "nightly".
EOF

doc "ops/access-review.md" <<'EOF'
---
title: Access review — how we do it
fixture: cortex-seed
---

Quarterly, per tier. The question is not "should this person have access" but
"if this account were taken over tonight, what would the attacker reach".

Tier 1 is the short list and gets read carefully. Tiers 3 and 4 get skimmed for
accounts that have not authenticated in 90 days, which are disabled rather than
deleted — deletion loses the audit trail.
EOF

doc "ops/laptop-setup.md" <<'EOF'
---
title: Laptop setup notes
fixture: cortex-seed
---

Full-disk encryption before anything else goes on the machine; retrofitting it
means the pre-encryption blocks stay recoverable.

Then: password manager, SSO enrolment with a hardware key AND a software TOTP as
the backup factor, and only then the working tools. The order matters because
enrolling a second factor from an already-compromised machine proves nothing.
EOF

doc "ops/printer-and-post.md" <<'EOF'
---
title: Printer and post
fixture: cortex-seed
---

Contracts that need a wet signature go out by post on Tuesdays and Thursdays;
everything else is signed electronically.

The scanner defaults to 300 dpi colour, which produces 12 MB files nobody can
e-mail. 200 dpi greyscale is legible for text and roughly a tenth of the size.
EOF

doc "projects/website-refresh-brief.md" <<'EOF'
---
title: Website refresh — brief
fixture: cortex-seed
---

Goal is not a redesign. The current site reads as a brochure and the traffic that
matters arrives already knowing what we do; what it cannot find is how to start.

Success is one thing: a visitor can get to a first conversation in two clicks
from any page. Everything else is decoration and should be argued for
separately.
EOF

doc "projects/knowledge-base-migration.md" <<'EOF'
---
title: Knowledge base migration
fixture: cortex-seed
---

The old wiki has about 400 pages of which maybe 90 are current. Migrating all of
it would import the rot along with the value.

Approach: migrate nothing wholesale. Move a page the first time somebody needs
it, updating it as it moves. After a quarter, whatever has not moved was not
needed, and can be archived without ceremony.
EOF

doc "projects/office-move-checklist.md" <<'EOF'
---
title: Office move checklist
fixture: cortex-seed
---

Internet first — order the line the day the lease is signed, because six weeks
of lead time is normal and everything else can be improvised.

Then: registered-address change with the trade register, invoicing address on
every recurring supplier, delivery address wherever it differs from billing, and
the post redirect. The last one is the one that always gets forgotten.
EOF

doc "projects/hiring-notes.md" <<'EOF'
---
title: Hiring notes
fixture: cortex-seed
---

The best signal so far has been asking a candidate to explain something they
built that did not work, and why. People who can narrate a failure precisely
tend to debug precisely.

The worst signal has been years of experience. It correlates with nothing we
care about and it anchors the salary conversation before the work is understood.
EOF

doc "reference/tooling-decisions.md" <<'EOF'
---
title: Tooling decisions and why
fixture: cortex-seed
---

Self-hosted where the data is ours and the operational cost is bounded; managed
where an outage would be a business problem and we could not fix it faster than
a vendor could.

That line moves. It moved once already when the backup story got good enough to
make self-hosting the mail archive reasonable, and it will move again.
EOF

doc "reference/document-retention.md" <<'EOF'
---
title: Document retention
fixture: cortex-seed
---

Accounting documents: ten years. Contracts: the contract term plus the
limitation period, which in practice means "do not delete contracts".

Everything else defaults to three years and is reviewed rather than deleted
automatically. Automatic deletion of things nobody classified is how you lose the
one document that mattered.
EOF

doc "reference/naming-conventions.md" <<'EOF'
---
title: File naming
fixture: cortex-seed
---

ISO dates, leading, always: 2026-07-29-thing.md sorts correctly forever and
2907-thing.md does not.

Lowercase, hyphens, no spaces. Spaces survive every modern tool right up until
the one shell script that does not quote its variables, and then they do not.
EOF

doc "reference/meeting-hygiene.md" <<'EOF'
---
title: Meeting hygiene
fixture: cortex-seed
---

A meeting without a written outcome did not happen. The note does not need to be
long — decision, owner, date is enough, and it goes in the notes folder the same
day.

If nobody can write the decision down afterwards, that is evidence the meeting
did not reach one, and the honest move is to say so rather than schedule a
follow-up on the assumption it did.
EOF

doc "reference/customer-communication.md" <<'EOF'
---
title: Customer communication
fixture: cortex-seed
---

Answer within one business day even when the answer is "we are looking at it and
will know more on Thursday". Silence is read as trouble whether or not there is
trouble.

For anything that went wrong: what happened, what it affected, what we are doing,
and when the next update comes. In that order, without adjectives.
EOF

doc "reference/glossary.md" <<'EOF'
---
title: Working glossary
fixture: cortex-seed
---

Tenant — one customer's isolated slice of the estate, including its own data
root and its own user trees.

Converge — a full playbook run that brings the estate to the declared state. Not
a deployment; a reconciliation, which is why running it twice is meant to be
boring the second time.

Corpus — the set of knowledge rows a store holds. Two stores holding the same
corpus is a measurable claim, and is measured nightly.
EOF

doc "personal/reading-list.md" <<'EOF'
---
title: Reading list
fixture: cortex-seed
---

Started but not finished: two books on distributed systems that both turn into
reference works around chapter four. Finishing them cover to cover is probably
the wrong goal.

Actually finished and worth it: the short one on writing plainly. Most of what it
says about sentences applies unchanged to commit messages.
EOF

doc "personal/travel-notes.md" <<'EOF'
---
title: Travel notes
fixture: cortex-seed
---

Prague by train rather than car for anything ending after 18:00 — the drive back
is where the mistakes happen.

Receipts photographed the same day, not at the end of the trip. A month later
the thermal paper from a motorway service station is a blank rectangle.
EOF

doc "personal/workshop-inventory.md" <<'EOF'
---
title: Workshop inventory
fixture: cortex-seed
---

Two drills, one of which has a dead battery pack that is no longer manufactured;
the tool is fine and the battery is the whole problem, which is most of what is
wrong with cordless tools.

Consumables worth keeping stocked: sandpaper in the two grits actually used,
and nothing else. Everything else gets bought per job and lives in a drawer.
EOF

doc "personal/garden-log.md" <<'EOF'
---
title: Garden log
fixture: cortex-seed
---

The south bed dried out twice in July despite mulch. Either the mulch layer is
too thin or the drip line has a blockage upstream — checking the far end first
next time, since a blocked line looks exactly like a thirsty plant.

Tomatoes did well, beans did not, and the difference was almost certainly the
week they went in rather than anything done afterwards.
EOF

n=$(find "$TARGET" -type f -name '*.md' | wc -l | tr -d ' ')
bytes=$(find "$TARGET" -type f -name '*.md' -exec cat {} + | wc -c | tr -d ' ')
echo "seeded ${n} markdown file(s), ${bytes} bytes, under ${TARGET}"

# ── Kick the ingest so this does not wait on the 300 s interval ──────────────
if [ -n "${KEAP_AGENT_TOKEN_RW:-}" ]; then
  curl -fsS -X POST -H "Authorization: Bearer ${KEAP_AGENT_TOKEN_RW}" \
    "${KEAP_URL}/agent/v1/fs/sync" | head -c 400; echo
else
  echo "NOTE: no KEAP RW token (neither exported nor in ${WING_DB}) — fs-sync not kicked;"
  echo "      the 300 s interval will pick the files up regardless."
fi

# ── Optional: measure it now, WITHOUT recording a night ──────────────────────
if [ "$MODE" = "check" ]; then
  echo
  echo "── running the feeders in the nightly's own order, each with its own env ──"
  # 04:15 consolidate → 04:30 cortex-fs-sync → 04:45 embed-sync → 05:30 diff.
  # The order is the contract: the diff is scheduled after embed-sync has run
  # BOTH passes precisely so it sees two settled corpora, not a mid-embed one.
  for job in keap-consolidate cortex-fs-sync keap-embed-sync; do
    echo "── ${job}"
    env_lines="$(job_env "$job")" || { echo "   SKIPPED — no rendered env (has the playbook run?)"; continue; }
    ( eval "$env_lines"; "${REPO_ROOT}/files/anatomy/scripts/${job}.py" ) \
      || echo "   ${job}: non-zero — read the output above before trusting the diff"
  done
  echo "── cortex-corpus-diff (--no-ledger)"
  env_lines="$(job_env cortex-corpus-diff)" || { echo "no rendered env for the diff — aborting"; exit 1; }
  ( eval "$env_lines"; "${REPO_ROOT}/files/anatomy/scripts/cortex-corpus-diff.py" --no-ledger )
  echo
  echo "The line above is a DIAGNOSTIC. --no-ledger means agreeStreak is untouched:"
  echo "  AGREES     -> leave the fixtures in place; tonight's night measures a real denominator."
  echo "  DISAGREES  -> either purge (--purge) and let the night run on the old set,"
  echo "                or keep them and accept a deliberate restart, having found a real bug."
fi
