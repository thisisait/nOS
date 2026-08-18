<?php

declare(strict_types=1);

namespace App\Model;

/**
 * A writer tried to append an UNSIGNED row to a chained audit log.
 *
 * Its own class so callers can tell it apart from an ordinary insert failure,
 * because the two deserve opposite handling. A disk error or a lock timeout is
 * transient: log it, let the run continue, the audit trail has a hole but the
 * log is still a log. THIS is not transient — it means the run is producing
 * history that cannot be verified, and every row it writes moves the chain's
 * break further from the cause.
 *
 * MEASURED 2026-08-16: `AuditEmitter` caught `\Throwable` and continued, on the
 * reasoning that "we never want to crash the agent because a single insert
 * failed". Sound for the transient case and wrong for this one — the librarian
 * finished its run, exit 0, having appended 37 unsigned rows, and the nightly
 * verify has failed every night since. Nothing in the run said so.
 *
 * The estate's own rule, from `docs/hidden_fees/07`: a step that cannot do its
 * job must not exit 0. An agent that cannot be audited cannot do its job.
 */
final class UnchainedAuditWrite extends \RuntimeException
{
}
