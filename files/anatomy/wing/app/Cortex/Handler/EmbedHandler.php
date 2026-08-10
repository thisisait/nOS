<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

/**
 * `embed` — present, typed, and waiting on the executor, not on KEAP.
 *
 * The class exists so the D3 coverage gate stays green and Wing boots; the body
 * lives in {@see LateBoundHandler}, which records the measurement, the false
 * conclusion it first produced, and the real blocker underneath.
 */
final class EmbedHandler extends LateBoundHandler
{
    public function opcode(): string
    {
        return 'embed';
    }

    public function acceptedNamespaces(): array
    {
        return ['tax', 'doc'];
    }

    protected function awaiting(): string
    {
        return 'stage-to-stage row threading AND a KEAP route that computes an embedding for supplied text — /embeddings/pending is the queue and POST /embeddings is a write, so this verb is the one genuinely blocked upstream too';
    }
}
