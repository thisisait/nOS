<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

/**
 * `filter` — present, typed, and waiting on the executor, not on KEAP.
 *
 * The class exists so the D3 coverage gate stays green and Wing boots; the body
 * lives in {@see LateBoundHandler}, which records the measurement, the false
 * conclusion it first produced, and the real blocker underneath.
 */
final class FilterHandler extends LateBoundHandler
{
    public function opcode(): string
    {
        return 'filter';
    }

    public function acceptedNamespaces(): array
    {
        return ['tax'];
    }

    protected function awaiting(): string
    {
        return 'stage-to-stage row threading; filtering needs no KEAP call at all, '
            . 'only the rows the previous stage produced';
    }
}
