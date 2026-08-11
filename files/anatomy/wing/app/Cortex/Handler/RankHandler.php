<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;
use App\Model\KeapCortexClient;

/**
 * `rank` — order the input by a signal.
 *
 * ONE upstream call, not one per row. `by` is asked of KEAP's hybrid search once
 * with a generous limit; the answer becomes a position map, and the input is
 * ordered by where each row appears in it. The alternative — searching once per
 * input row to discover its score — is N calls to learn an ordering KEAP already
 * computed in one, and it would make a five-row rank cost five round trips.
 *
 * ROWS THE SIGNAL DID NOT MENTION KEEP THEIR ORDER, AT THE BACK, AND SAY SO.
 * This is the decision worth defending: a row absent from a search result has no
 * measured relevance, which is not the same as low relevance. Sorting it to the
 * end is a presentation choice; pretending it scored zero would be a claim. Each
 * such row carries `rankSignal: null`, so `… | rank by=x | filter where=…` can
 * tell "ranked last" from "never scored".
 *
 * WITHOUT `by` THERE IS NO SIGNAL. The grammar makes it optional, and the honest
 * response to its absence is a refusal rather than an arbitrary order: returning
 * the input in the order it arrived, labelled as ranked, would be the most
 * quietly wrong thing this verb could do.
 *
 * `limit` TRUNCATES AFTER ORDERING, which is the only order of operations that
 * makes `limit` mean "the best n" rather than "n arbitrary rows, sorted".
 */
final class RankHandler implements CortexHandlerInterface
{
    /** Signal depth. Generous, because a row past this is reported unscored. */
    private const SIGNAL_DEPTH = 50;

    public function __construct(private readonly KeapCortexClient $keap)
    {
    }

    public function opcode(): string
    {
        return 'rank';
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
        // `nothingToOperateBy`, not `pipeBroken`. A handler only ever sees
        // `!hasInput()` at STAGE 0 — the executor short-circuits a real break
        // before the handler runs — so there is no predecessor to have broken.
        // Reporting a broken pipe here would send the caller looking for a
        // failing stage that does not exist; the actual fault is a chain that
        // opens with a verb defined over an input it never provides.
        if (!$ctx->hasInput()) {
            return CortexStageResult::nothingToOperateBy(
                "'rank' orders its input and received none. An empty ordering is "
                . 'not an ordering of nothing.'
            );
        }

        // An input ARRIVED and was empty. That is an answer from the stage
        // before, not an absence here, so the honest reply is zero rows rather
        // than a refusal — see CortexContext::inputIsEmpty().
        if ($ctx->inputIsEmpty()) {
            return CortexStageResult::read([], 0);
        }

        $by = trim((string) $stage->param('by', ''));
        if ($by === '') {
            foreach ($stage->operands as $o) {
                $by = trim((string) ($o['resolvedName'] ?? $o['surface'] ?? $o['id'] ?? ''));
                if ($by !== '') {
                    break;
                }
            }
        }
        if ($by === '') {
            return CortexStageResult::nothingToOperateBy(
                "'rank' was given no `by` and no operand, so there is no signal to "
                . 'order by. Returning the input in arrival order and calling it '
                . 'ranked would be a claim about relevance nobody made.'
            );
        }

        $hit = $this->keap->semanticSearch($by, self::SIGNAL_DEPTH);
        if ($hit === null) {
            return CortexStageResult::upstreamUnreachable(sprintf(
                "'rank' could not obtain a signal: KEAP's hybrid search did not "
                . "answer for '%s'. The input is returned by no one; nothing was ordered.",
                $by
            ));
        }

        $position = [];
        $score = [];
        $i = 0;
        foreach ($hit['results'] as $r) {
            if (!is_array($r)) {
                continue;
            }
            foreach (['id', 'nodeId', 'name'] as $key) {
                $v = $r[$key] ?? null;
                if (is_string($v) && $v !== '' && !isset($position[mb_strtolower($v)])) {
                    $position[mb_strtolower($v)] = $i;
                    $score[mb_strtolower($v)] = (float) ($r['score'] ?? 0.0);
                }
            }
            $i++;
        }

        // Decorate before sorting, so the sort is over a value each row carries
        // and the caller can see the same number the order was made from.
        $decorated = [];
        foreach (array_values($ctx->input) as $arrival => $row) {
            $key = $this->identify($row);
            $has = $key !== null && isset($position[$key]);
            $decorated[] = [
                'row' => $row + [
                    'rankSignal' => $has ? $score[$key] : null,
                    'rankBy' => $by,
                ],
                'pos' => $has ? $position[$key] : PHP_INT_MAX,
                'arrival' => $arrival,
            ];
        }

        // Stable: arrival order breaks ties, so the unscored tail keeps the shape
        // it came in with instead of being shuffled by the sort's internals.
        usort($decorated, static fn (array $a, array $b): int
            => [$a['pos'], $a['arrival']] <=> [$b['pos'], $b['arrival']]);

        $rows = array_map(static fn (array $d): array => $d['row'], $decorated);

        $limit = (int) $stage->param('limit', 0);
        if ($limit > 0) {
            $rows = array_slice($rows, 0, min($limit, 200));
        }

        return CortexStageResult::read($rows, count($ctx->input));
    }

    /**
     * The key this row is looked up by in the signal.
     *
     * @param array<string,mixed> $row
     */
    private function identify(array $row): ?string
    {
        foreach (['id', 'nodeId', 'name', 'resolvedName'] as $key) {
            $v = $row[$key] ?? null;
            if (is_string($v) && $v !== '') {
                return mb_strtolower($v);
            }
        }
        return null;
    }
}
