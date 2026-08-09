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
    public function __construct(
        public readonly ?string $actorId,
        public readonly string $tenant,
        public readonly string $actionId,
        public readonly ?string $traceId = null,
    ) {
    }
}
