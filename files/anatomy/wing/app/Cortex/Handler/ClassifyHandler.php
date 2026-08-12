<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;
use App\Model\KeapCortexClient;

/**
 * `classify` — assign the input to an ontology node.
 *
 * One KEAP hybrid search per input row (`GET /agent/v1/search/semantic`, 200 to
 * the RO bearer), taking the best-scoring taxonomy hit as the assignment. The
 * verb was never blocked on that route; it was blocked on having an input, which
 * the executor did not provide until 2026-08-11.
 *
 * THE ASSIGNMENT IS ATTACHED, NOT SUBSTITUTED. The row that comes out is the row
 * that went in plus `classifiedAs` / `classifyScore` / `classifyBy`. A verb that
 * replaced its input with the node would make `… | classify | filter where=…`
 * filter the ONTOLOGY rather than the things being classified, which is the
 * opposite of what the chain says.
 *
 * `threshold` IS AN INTEGER PERCENT, because that is what the grammar declares
 * (`{ threshold: { type: 'int' } }`) and KEAP's scores are floats in [0,1]. The
 * conversion happens here, once, and is stated: `threshold=70` means 0.70. A row
 * scoring below it is returned UNASSIGNED rather than dropped — dropping would
 * make `classify` a filter, and the chain already has one of those.
 *
 * THE OPERAND IS THE SUBTREE, and it is mandatory because the grammar says so
 * (`operands: { min: 1, max: 1 }`). It bounds where an assignment may land:
 * `classify(tax:01)` assigns within 01 and nowhere else. The first draft of this
 * handler ignored operands entirely — it would have parsed, dispatched, and
 * quietly assigned rows anywhere in the ontology while the chain named a scope.
 * A verb that accepts an argument it does not read is worse than one that
 * refuses it, because the caller's constraint is visible in the source and
 * absent from the behaviour.
 *
 * WHAT IS NOT CLAIMED. KEAP's hybrid search has three legs (lexical, vector,
 * graph) and reports which ran. A purely lexical answer read as a semantic one
 * is a real way to overstate this verb, so `legs` is carried onto every row and
 * a caller can see what the assignment was actually made of.
 */
final class ClassifyHandler implements CortexHandlerInterface
{
    /** Input rows classified per stage — one upstream call each. */
    private const MAX_INPUT = 25;

    /** Hits fetched per row. Only the best is used; a few give it something to beat. */
    private const CANDIDATES = 5;

    public function __construct(private readonly KeapCortexClient $keap)
    {
    }

    public function opcode(): string
    {
        return 'classify';
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
                "'classify' assigns its input to an ontology node and received no "
                . 'input. Nothing was classified, and no rows is not the same as '
                . 'nothing being classifiable.'
            );
        }

        // An input ARRIVED and was empty. That is an answer from the stage
        // before, not an absence here, so the honest reply is zero rows rather
        // than a refusal — see CortexContext::inputIsEmpty().
        if ($ctx->inputIsEmpty()) {
            return CortexStageResult::read([], 0);
        }

        $threshold = (int) $stage->param('threshold', 0);
        $threshold = max(0, min($threshold, 100)) / 100.0;

        // The scope the caller named. Guaranteed present by the grammar's arity
        // rule, but read defensively: a handler that assumes an operand and gets
        // none would classify across the whole ontology, which is the failure
        // this argument exists to prevent.
        $scope = '';
        foreach ($stage->operands as $o) {
            $scope = (string) ($o['id'] ?? $o['surface'] ?? '');
            if ($scope !== '') {
                break;
            }
        }
        if ($scope === '') {
            return CortexStageResult::nothingToOperateBy(
                "'classify' takes the ontology subtree to assign within, and this "
                . 'stage carries no usable operand. Assigning anywhere would '
                . 'ignore the scope the chain names.'
            );
        }

        $visited = array_slice($ctx->input, 0, self::MAX_INPUT);
        // The cap was SILENT until 2026-08-12: 40 rows in, 25 classified, and
        // nothing anywhere said so — the exact shape MapHandler's cap comment
        // condemns, standing uncorrected one file over. Reported via `meta`
        // (the handler's own channel), never as a pseudo-row the pipe would
        // carry downstream as input.
        $truncated = max(0, count($ctx->input) - count($visited));
        $rows = [];
        $answered = 0;
        $unanswered = 0;

        foreach ($visited as $row) {
            $text = $this->describe($row);
            if ($text === null) {
                $rows[] = $row + ['classifiedAs' => null, 'classifyNote' => 'no text to classify'];
                continue;
            }

            $hit = $this->keap->semanticSearch($text, self::CANDIDATES);
            if ($hit === null) {
                $unanswered++;
                $rows[] = $row + ['classifiedAs' => null, 'classifyNote' => 'KEAP search did not answer'];
                continue;
            }
            $answered++;

            $best = $this->best($hit['results'], $scope);
            if ($best === null || (float) ($best['score'] ?? 0.0) < $threshold) {
                $rows[] = $row + [
                    'classifiedAs' => null,
                    'classifyScore' => $best === null ? null : (float) ($best['score'] ?? 0.0),
                    'classifyNote' => $best === null
                        ? 'no taxonomy candidate'
                        : sprintf('below threshold %.2f', $threshold),
                    'classifyLegs' => $hit['legs'],
                ];
                continue;
            }

            $rows[] = $row + [
                'classifiedAs' => $best['id'] ?? null,
                'classifiedAsName' => $best['name'] ?? $best['title'] ?? null,
                'classifyScore' => (float) ($best['score'] ?? 0.0),
                'classifyBy' => $text,
                'classifyLegs' => $hit['legs'],
            ];
        }

        // Not one upstream answer. Rows carrying `classifiedAs: null` would read
        // as "nothing matched"; this says the classifier never ran.
        if ($answered === 0) {
            return CortexStageResult::upstreamUnreachable(sprintf(
                "'classify' got no answer from KEAP for any of its %d input "
                . 'row(s). Unclassified and unasked are different states.',
                count($visited)
            ));
        }

        $meta = [];
        if ($truncated > 0) {
            $meta['truncated_input'] = $truncated;
            $meta['input_cap'] = self::MAX_INPUT;
        }
        // Per-row upstream failures are already visible on the rows themselves
        // (`classifyNote`), so only the aggregate rides here. Counted where the
        // null happened, NOT derived as visited-minus-answered: a row with no
        // text to classify was never ASKED, and folding it into "unanswered"
        // would misreport a caller-data gap as an upstream one.
        if ($unanswered > 0) {
            $meta['unanswered_input'] = $unanswered;
        }

        return CortexStageResult::read($rows, count($visited), $meta);
    }

    /**
     * The text this row should be classified BY.
     *
     * Ordered most-specific first. A row with a summary is better classified by
     * its summary than by its id, and an id-only row is better classified by its
     * id than not at all.
     *
     * @param array<string,mixed> $row
     */
    private function describe(array $row): ?string
    {
        foreach (['summary', 'description', 'title', 'name', 'resolvedName', 'id'] as $key) {
            $v = $row[$key] ?? null;
            if (is_string($v) && trim($v) !== '') {
                return trim($v);
            }
        }
        return null;
    }

    /**
     * The best TAXONOMY candidate, which is not simply the first result.
     *
     * Hybrid search returns objects and captures alongside taxonomy nodes, and
     * assigning a row to a capture would be an assignment to something that is
     * not part of the ontology at all.
     *
     * @param list<array<string,mixed>> $results
     * @param string $scope dotted taxonomy path the assignment must fall under
     * @return array<string,mixed>|null
     */
    private function best(array $results, string $scope): ?array
    {
        $prefix = mb_strtolower($scope);
        foreach ($results as $r) {
            if (!is_array($r)) {
                continue;
            }
            $kind = (string) ($r['kind'] ?? $r['type'] ?? '');
            if ($kind !== '' && !str_contains(mb_strtolower($kind), 'taxonomy')) {
                continue;
            }
            $id = mb_strtolower((string) ($r['id'] ?? ''));
            // Dotted-path containment, and the dot matters: without it `01` would
            // also claim `010`, which is a different branch of the taxonomy.
            if ($id !== $prefix && !str_starts_with($id, $prefix . '.')) {
                continue;
            }
            return $r;
        }
        return null;
    }
}
