<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;

/**
 * `show` (v3) — a sink that changes nothing. Rows pass through untouched and
 * the render spec travels in `meta.render`, never as a row, so a later stage
 * still reads data. Numbers are never computed here.
 */
final class ShowHandler implements CortexHandlerInterface
{
    private const KINDS = ['chart', 'kpi', 'choice', 'table', 'list', 'record'];
    private const SPEC = ['chart', 'x', 'y', 'title', 'unit'];

    public function opcode(): string
    {
        return 'show';
    }

    public function mutating(): bool
    {
        return false;
    }

    public function acceptedNamespaces(): array
    {
        return [];
    }

    public function execute(ResolvedStage $stage, CortexContext $ctx): CortexStageResult
    {
        if (!$ctx->hasInput()) {
            return CortexStageResult::nothingToOperateBy("'show' renders its input and received none.");
        }
        $kind = (string) $stage->param('kind', '');
        if (!in_array($kind, self::KINDS, true)) {
            return CortexStageResult::nothingToOperateBy(
                "'show' kind must be one of " . implode('|', self::KINDS) . ", got '{$kind}'."
            );
        }
        $render = ['kind' => $kind];
        foreach (self::SPEC as $key) {
            $v = $stage->param($key);
            if ($v !== null && $v !== '') {
                $render[$key] = (string) $v;
            }
        }
        return CortexStageResult::read(array_values($ctx->input), 0, ['render' => $render]);
    }
}
