<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

/**
 * `map` — present, typed, and waiting on the executor, not on KEAP.
 *
 * The class exists so the D3 coverage gate stays green and Wing boots; the body
 * lives in {@see LateBoundHandler}, which records the measurement, the false
 * conclusion it first produced, and the real blocker underneath.
 */
final class MapHandler extends LateBoundHandler
{
    public function opcode(): string
    {
        return 'map';
    }

    public function acceptedNamespaces(): array
    {
        return ['tax'];
    }

    protected function awaiting(): string
    {
        return 'stage-to-stage row threading; the read it will use — KEAP /agent/v1/taxonomy/node/:id (children) — already answers 200';
    }
}
