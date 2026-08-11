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
    ) {
    }

    /**
     * A stage defined over its input, reached with none, is not a stage over an
     * empty world.
     *
     * The distinction this method exists to keep: `filter` over zero rows could
     * legitimately return zero rows, and that is indistinguishable from `filter`
     * never having been given anything. The first is an answer; the second is a
     * broken pipe. Handlers ask this before working, and return an `unavailable`
     * rather than a confident nothing.
     */
    public function hasInput(): bool
    {
        return $this->input !== [];
    }
}
