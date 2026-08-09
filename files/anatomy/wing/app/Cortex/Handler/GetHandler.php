<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;
use App\Model\KeapCortexClient;

/**
 * `get` — fetch what an operand names.
 *
 * P1 reaches the two read surfaces KEAP actually publishes to an agent bearer,
 * measured 2026-08-09 rather than taken from the design's table:
 *
 *     /agent/v1/relations   200   4643 toe + 441 curated
 *     /agent/v1/objects     200   365
 *     /agent/v1/taxonomy    401   (both RO and RW — no such route)
 *     /agent/v1/nodes       401   (likewise)
 *     /agent/v1/search      401   (likewise)
 *
 * So `rel:` is served from `relations`, and a `tax:` operand returns the
 * resolution KEAP already carried in the AST rather than pretending to fetch a
 * node from an endpoint that does not exist. That is a narrower answer than the
 * design imagined, and it is the honest one: the alternative is a handler that
 * returns empty rows and reads like a successful query over an empty world.
 */
final class GetHandler implements CortexHandlerInterface
{
    public function __construct(private readonly KeapCortexClient $keap)
    {
    }

    public function opcode(): string
    {
        return 'get';
    }

    public function mutating(): bool
    {
        return false;
    }

    public function acceptedNamespaces(): array
    {
        return ['tax', 'rel'];
    }

    public function execute(ResolvedStage $stage, CortexContext $ctx): CortexStageResult
    {
        $limit = (int) ($stage->params['limit'] ?? 20);
        $limit = max(1, min($limit, 200));

        $rows = [];
        foreach ($stage->operands as $o) {
            $ns = (string) ($o['ns'] ?? '');
            if ($ns === 'rel') {
                $fetched = $this->keap->relations((string) ($o['id'] ?? $o['surface'] ?? ''), $limit);
                if ($fetched === null) {
                    return CortexStageResult::unavailable(
                        'KEAP /agent/v1/relations did not answer; nothing was read'
                    );
                }
                foreach ($fetched as $r) {
                    $rows[] = $r;
                }
                continue;
            }
            // tax: KEAP publishes no node-fetch route, so the AST's own
            // resolution is the whole truth we have. Returned as-is and
            // labelled, so a caller can tell it apart from a node body.
            $rows[] = [
                'ns' => $ns,
                'id' => $o['id'] ?? null,
                'resolvedName' => $o['resolvedName'] ?? null,
                'note' => 'resolution only — KEAP publishes no node-fetch route',
            ];
        }
        return CortexStageResult::read(array_slice($rows, 0, $limit), count($rows));
    }
}
