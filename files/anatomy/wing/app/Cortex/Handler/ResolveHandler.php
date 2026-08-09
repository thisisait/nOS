<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;

/**
 * `resolve` — echo what KEAP already decided each operand means.
 *
 * The cheapest verb and the only one that is complete in P1 without a single
 * downstream call, because KEAP resolves `tax:` and `rel:` operands during
 * validation and carries the answer in the AST. Measured on the live estate:
 *
 *     tax:01 -> {"ns":"tax","kind":"resolved","binding":"exact",
 *                "surface":"01","id":"01","resolvedName":"Natural Sciences"}
 *
 * So this handler introduces NO new resolution authority — that is the point.
 * If it looked anything up itself there would be two places deciding what
 * `tax:01` means, and this repository has spent a week paying for that shape.
 */
final class ResolveHandler implements CortexHandlerInterface
{
    public function opcode(): string
    {
        return 'resolve';
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
        $rows = [];
        foreach ($stage->operands as $o) {
            $rows[] = [
                'ns' => $o['ns'] ?? null,
                'surface' => $o['surface'] ?? null,
                'id' => $o['id'] ?? null,
                'resolvedName' => $o['resolvedName'] ?? null,
                'kind' => $o['kind'] ?? null,
                'binding' => $o['binding'] ?? null,
            ];
        }
        return CortexStageResult::read($rows, count($rows));
    }
}
