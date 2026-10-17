<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;

/**
 * `aggregate` (v3) — count|sum|avg over the INPUT, optionally grouped by `by`.
 * A `db:` operand is thalamus's path (query_rows op), so Wing accepts none (422).
 * Rows are `{<by>: group, <op>: value}` in first-seen order; a non-numeric `y`
 * is left out of sum/avg and counted in `meta.skipped`.
 */
final class AggregateHandler implements CortexHandlerInterface
{
    private const OPS = ['count', 'sum', 'avg'];

    public function opcode(): string
    {
        return 'aggregate';
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
            return CortexStageResult::nothingToOperateBy(
                "'aggregate' reduces its input and received none."
            );
        }
        $op = (string) $stage->param('op', '');
        $by = trim((string) $stage->param('by', ''));
        $y = trim((string) $stage->param('y', ''));
        if (!in_array($op, self::OPS, true)) {
            return CortexStageResult::nothingToOperateBy(
                "'aggregate' op must be one of " . implode('|', self::OPS) . ", got '{$op}'."
            );
        }
        if ($op !== 'count' && $y === '') {
            return CortexStageResult::nothingToOperateBy(
                "'aggregate' op={$op} needs `y`, the column to {$op}."
            );
        }

        /** @var array<string,array{key:mixed,n:int,sum:float|int}> $groups */
        $groups = [];
        $skipped = 0;
        foreach ($ctx->input as $row) {
            $key = $by === '' ? null : ($row[$by] ?? null);
            $g = $by === '' ? '' : json_encode($key);
            $groups[$g] ??= ['key' => $key, 'n' => 0, 'sum' => 0];
            if ($op === 'count') {
                $groups[$g]['n']++;
                continue;
            }
            $v = $row[$y] ?? null;
            if (!is_numeric($v)) {
                $skipped++;
                continue;
            }
            $groups[$g]['n']++;
            $groups[$g]['sum'] += $v + 0;
        }
        if ($groups === [] && $by === '') {
            $groups[''] = ['key' => null, 'n' => 0, 'sum' => 0];
        }

        $rows = [];
        foreach ($groups as $g) {
            $value = match ($op) {
                'count' => $g['n'],
                'sum' => $g['sum'],
                'avg' => $g['n'] > 0 ? $g['sum'] / $g['n'] : null,
            };
            $rows[] = ($by === '' ? [] : [$by => $g['key']]) + [$op => $value];
        }
        return CortexStageResult::read($rows, count($ctx->input), $skipped > 0 ? ['skipped' => $skipped] : []);
    }
}
