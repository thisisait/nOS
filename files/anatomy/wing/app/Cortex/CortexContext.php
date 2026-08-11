<?php

declare(strict_types=1);

namespace App\Cortex;

/**
 * What a handler is allowed to know.
 *
 * Deliberately thin. Scope was enforced at the token boundary before any
 * handler was reached, so nothing here carries scopes, and nothing here carries
 * the raw bearer — a handler that could read the caller's token could widen its
 * own reach, and the whole point of the capability model is that it cannot.
 *
 * `actionId` is the audit lineage handle: one per stage, minted before the
 * handler runs and closed after it returns, so a single
 * `SELECT … WHERE actor_action_id = ?` reconstructs what one stage did.
 */
final class CortexContext
{
    /**
     * @param list<array<string,mixed>> $input rows the PREVIOUS stage produced —
     *        the `@prev` the surface syntax's `|` always implied and the executor
     *        never filled. Empty for the first stage, which is why `get` and
     *        `resolve` (the two verbs needing no input) were the only two that
     *        ever ran.
     */
    public function __construct(
        public readonly ?string $actorId,
        public readonly string $tenant,
        public readonly string $actionId,
        public readonly ?string $traceId = null,
        public readonly array $input = [],
        public readonly bool $inputOffered = false,
    ) {
    }

    /**
     * Was this stage handed an input at all?
     *
     * THE DISTINCTION THIS EXISTS FOR, and it took two attempts to get right.
     * `filter` over zero rows could legitimately return zero rows, and that is
     * indistinguishable from `filter` never having been given anything. The
     * first is an answer; the second is a broken pipe.
     *
     * The first cut asked `input !== []`, which collapsed exactly the two cases
     * the paragraph above separates: a predecessor that ran and honestly matched
     * nothing was treated as a break, so the honest zero this design defends was
     * unreachable through a pipe. `inputOffered` is set by the executor for
     * every stage after the first, independently of how many rows arrived, so
     * `offered && input === []` is an answer and `!offered` is a stage 0 that
     * had no predecessor to be defined over.
     */
    public function hasInput(): bool
    {
        return $this->inputOffered;
    }

    /** An input arrived and it was empty — an answer, not an absence. */
    public function inputIsEmpty(): bool
    {
        return $this->inputOffered && $this->input === [];
    }
}
