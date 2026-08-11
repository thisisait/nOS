<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;

/**
 * A verb the executor cannot yet run, and the honest reason why.
 *
 * THE REASON RECORDED HERE UNTIL 2026-08-10 WAS WRONG, and correcting it is
 * worth more than the five bodies it was standing in for. It said KEAP
 * publishes no read surface for `map`, `filter`, `rank`, `classify` and
 * `embed`, on the strength of a probe that found `/agent/v1/taxonomy`,
 * `/nodes`, `/search`, `/classify` and `/embed` all answering 401. The 401s
 * were real. The conclusion was not: the probe tested the paths the DESIGN
 * DOCUMENT named, and KEAP serves the same data at different ones —
 * `/agent/v1/taxonomy/node/:id`, `/agent/v1/taxonomy/search` and
 * `/agent/v1/search/semantic` all answer 200 to the RO bearer. A 401 from the
 * forward-auth catch-all on an unrouted path looks exactly like a scope
 * refusal, which is how a careful measurement still reached a false verdict.
 *
 * THE ACTUAL BLOCKER IS ONE LEVEL IN, and it is ours. Read the registry's own
 * summaries:
 *
 *     get       fetch the operand's record              <- no input
 *     resolve   resolve a surface term to an operand    <- no input
 *     map       project each item OF THE INPUT ...
 *     filter    keep the items OF THE INPUT that ...
 *     rank      order THE INPUT by a signal
 *     classify  assign THE INPUT to an ontology node
 *     embed     project THE INPUT into vector space
 *
 * The two verbs that executed were exactly the two that need no input, and the
 * five that did not were exactly the five that consume it. That correlation was
 * total, and it was not a fact about KEAP: `CortexExecutorPresenter` dispatched
 * each stage INDEPENDENTLY and collected the results side by side, so the `|` in
 * the surface syntax did not pipe and a verb defined over its input had none.
 *
 * FIXED 2026-08-11. `CortexContext` carries the previous stage's rows, the
 * executor threads them, and `map`, `filter`, `rank` and `classify` have bodies
 * against routes that answered all along. This class now has exactly one
 * subclass.
 *
 * `embed` carries a second, independent gap: KEAP has `GET /embeddings/pending`
 * (the queue) and `POST /embeddings` (a write of computed vectors), but no
 * route that computes an embedding for supplied text. That one really is
 * upstream, and it is the only one of the five that is.
 *
 * So the handler key EXISTS — the D3 coverage gate stays green, Wing does not
 * gate the estate on work it has not done — and every call says exactly what it
 * did not do. The day the executor threads rows between stages, four of these
 * five get a body and nothing else changes.
 */
abstract class LateBoundHandler implements CortexHandlerInterface
{
    /** What this verb is waiting on, named so the gap is legible at the call site. */
    abstract protected function awaiting(): string;

    public function mutating(): bool
    {
        return false;
    }

    public function execute(ResolvedStage $stage, CortexContext $ctx): CortexStageResult
    {
        return CortexStageResult::unavailable(sprintf(
            "'%s' is published, legal and has no surface to call. Waiting on: %s. "
            . 'Nothing was read.',
            $this->opcode(),
            $this->awaiting()
        ));
    }
}
