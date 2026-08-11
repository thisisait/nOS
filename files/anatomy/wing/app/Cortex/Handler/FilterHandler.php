<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;

/**
 * `filter` — keep the items of the input that match the operand.
 *
 * The one verb of the five that never needed an upstream. It reads the rows the
 * previous stage produced and nothing else; it was late-bound only because the
 * executor dispatched stages independently, so there was no input to keep any
 * part of. Threading rows (2026-08-11) gave it everything it ever required.
 *
 * WHAT MATCHING MEANS HERE, and the shape is deliberately small. Two things can
 * narrow a row set and both come from the AST:
 *
 *   - the OPERANDS, when present: keep rows whose identity is one of them. This
 *     is `… | filter tax:03.01` — an intersection against named things.
 *   - `where`, a param the grammar declares as a free string: a substring test
 *     over the row's own text, case-folded.
 *
 * NOT AN EXPRESSION LANGUAGE, and that is a decision rather than a shortcut. A
 * predicate language inside a param string would be a second grammar, unparsed
 * by `cortex-validate` and ungated by the binding gate — a place to smuggle
 * reach past the two things that authorise a chain. If `where` ever needs to
 * express more than "contains", it belongs in the AST as structure the validator
 * can see, not in a string this class interprets alone.
 *
 * NO OPERANDS AND NO `where` IS NOT A FILTER. It is almost certainly a mistake
 * on the caller's side, and silently returning the input unchanged would make
 * the chain read as though a filter had been applied. It refuses instead.
 */
final class FilterHandler implements CortexHandlerInterface
{
    public function opcode(): string
    {
        return 'filter';
    }

    public function mutating(): bool
    {
        return false;
    }

    public function acceptedNamespaces(): array
    {
        return ['tax'];
    }

    public function execute(ResolvedStage $stage, CortexContext $ctx): CortexStageResult
    {
        if (!$ctx->hasInput()) {
            return CortexStageResult::unavailable(
                "'filter' is defined over its input and received none. Zero rows "
                . 'kept and zero rows never offered are different facts, and this '
                . 'one is the second.'
            );
        }

        $where = trim((string) $stage->param('where', ''));
        $ids = [];
        foreach ($stage->operands as $o) {
            foreach (['id', 'surface', 'resolvedName'] as $key) {
                if (isset($o[$key]) && is_string($o[$key]) && $o[$key] !== '') {
                    $ids[mb_strtolower($o[$key])] = true;
                }
            }
        }

        if ($ids === [] && $where === '') {
            return CortexStageResult::unavailable(
                "'filter' was given neither operands nor a `where`, so there is "
                . 'nothing to keep BY. Returning the input unchanged would read as '
                . 'a filter that ran; nothing was filtered.'
            );
        }

        $kept = [];
        foreach ($ctx->input as $row) {
            if ($ids !== [] && !$this->identifies($row, $ids)) {
                continue;
            }
            if ($where !== '' && !$this->contains($row, $where)) {
                continue;
            }
            $kept[] = $row;
        }

        return CortexStageResult::read(array_values($kept), count($ctx->input));
    }

    /**
     * Is this row one of the named operands?
     *
     * Checked across the same key set the operands were read from, because a row
     * arriving from `get` carries `id`, one from `map` carries the child's `id`,
     * and one from `classify` carries the node it was assigned to. Matching on a
     * single key would make the verb work after one predecessor and not another.
     *
     * @param array<string,mixed>  $row
     * @param array<string,bool>   $ids
     */
    private function identifies(array $row, array $ids): bool
    {
        foreach (['id', 'nodeId', 'surface', 'resolvedName', 'name'] as $key) {
            $v = $row[$key] ?? null;
            if (is_string($v) && $v !== '' && isset($ids[mb_strtolower($v)])) {
                return true;
            }
        }
        return false;
    }

    /**
     * Case-folded substring test over the row's own scalar text.
     *
     * Scalars only, and one level deep: a recursive search would let `where=x`
     * match an id buried in a nested structure the caller never meant to search,
     * which is a quiet way for a filter to keep more than it says.
     *
     * @param array<string,mixed> $row
     */
    private function contains(array $row, string $needle): bool
    {
        $needle = mb_strtolower($needle);
        foreach ($row as $value) {
            if ((is_string($value) || is_numeric($value))
                && str_contains(mb_strtolower((string) $value), $needle)
            ) {
                return true;
            }
        }
        return false;
    }
}
