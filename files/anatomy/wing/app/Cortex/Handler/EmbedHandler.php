<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

/**
 * `embed` — present, typed, and waiting on a route KEAP does not publish.
 *
 * The class exists so the D3 coverage gate stays green and Wing boots; the body
 * lives in {@see LateBoundHandler}, which records what was measured and why a
 * typed absence beats an empty result set.
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

    protected function awaitingRoute(): string
    {
        return '/agent/v1/embed';
    }
}
