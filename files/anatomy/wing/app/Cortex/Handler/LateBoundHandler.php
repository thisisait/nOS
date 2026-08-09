<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;

/**
 * A verb whose handler exists and whose upstream read surface does not.
 *
 * WHY FIVE OF THE SEVEN P1 VERBS SIT HERE. docs/archive/nos-cortex-lang-wing-executor.md §3.4 gives each verb a
 * KEAP endpoint to adapt. Probed against the running estate on 2026-08-09 with
 * both the RO and RW agent bearers:
 *
 *     /agent/v1/relations        200        /agent/v1/taxonomy   401
 *     /agent/v1/objects          200        /agent/v1/nodes      401
 *     /agent/v1/captures         200        /agent/v1/search     401
 *     /agent/v1/validate         200        /agent/v1/classify   401
 *     /agent/v1/validate/opcodes 200        /agent/v1/embed      401
 *
 * The 401s answer identically for both tokens, which is a catch-all auth
 * middleware firing ahead of a route that is not there — not a scope refusal.
 * So `map`, `filter`, `rank`, `classify` and `embed` have nothing to adapt yet.
 *
 * The choice was between three bad options and this one. Not shipping the verbs
 * fails the D3 coverage gate and Wing refuses to boot. Shipping them returning
 * empty rows makes "no such endpoint" indistinguishable from "the query matched
 * nothing" — the estate's signature defect, absence rendering as calm. Deleting
 * them from KEAP's registry is someone else's repository.
 *
 * So the handler key EXISTS (coverage stays green, and Wing does not gate the
 * estate on an upstream it does not own) and every call says exactly what it
 * did not do. `late_binding_unavailable` is a typed absence, and the day KEAP
 * publishes the route the subclass gets a body and nothing else changes.
 */
abstract class LateBoundHandler implements CortexHandlerInterface
{
    /** The route this verb is waiting on, named so the gap is legible at the call site. */
    abstract protected function awaitingRoute(): string;

    public function mutating(): bool
    {
        return false;
    }

    public function execute(ResolvedStage $stage, CortexContext $ctx): CortexStageResult
    {
        return CortexStageResult::unavailable(sprintf(
            "'%s' needs KEAP %s, which this deployment does not publish "
            . '(measured 2026-08-09: 401 for both the RO and RW agent bearers, '
            . 'i.e. no route). Nothing was read.',
            $this->opcode(),
            $this->awaitingRoute()
        ));
    }
}
