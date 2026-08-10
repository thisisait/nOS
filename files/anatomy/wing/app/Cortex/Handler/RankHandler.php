<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

/**
 * `rank` — present, typed, and waiting on the executor, not on KEAP.
 *
 * The class exists so the D3 coverage gate stays green and Wing boots; the body
 * lives in {@see LateBoundHandler}, which records the measurement, the false
 * conclusion it first produced, and the real blocker underneath.
 */
final class RankHandler extends LateBoundHandler
{
    public function opcode(): string
    {
        return 'rank';
    }

    public function acceptedNamespaces(): array
    {
        return ['tax'];
    }

    protected function awaiting(): string
    {
        return 'stage-to-stage row threading; KEAP /agent/v1/search/semantic already returns ranked rows for the search-backed case';
    }
}
