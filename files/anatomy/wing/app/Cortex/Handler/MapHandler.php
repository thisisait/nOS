<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;
use App\Model\KeapCortexClient;

/**
 * `map` — project each item of the input through the operand.
 *
 * The projection this estate has a real read for is DESCENT: given nodes, take
 * their children. `GET /agent/v1/taxonomy/node/:id` answers 200 to the RO bearer
 * and carries `children`, so `tax:03 | map` is "the children of 03" and
 * `… | map | map` is a generation further down. That is the whole verb.
 *
 * WHY DESCENT AND NOT SOMETHING MORE GENERAL. `map` in the grammar declares no
 * params at all — there is no field in which a caller could name a different
 * projection, so inventing one here would be a capability addable by argument
 * rather than by code, which is the one rule the handler interface says may not
 * be relaxed. When a second projection is wanted it needs a param in
 * `cortex-opcodes.ts`, a validator that can see it, and a review — not a branch
 * in this file.
 *
 * THE OPERAND BOUNDS THE DESCENT, and this class shipped without reading it.
 * The grammar makes it mandatory (`operands: { min: 1, max: 1 }`), so
 * `get(tax:01) | map(tax:02)` parsed, passed the namespace gate, and returned
 * the children of 01 — the caller's constraint visible in the source and absent
 * from the behaviour. `ClassifyHandler`'s docblock condemns exactly that, in the
 * same commit; the doctrine and its violation shipped together, and the live
 * example chain happened to use `map(tax:01)` after `get(tax:01)`, the one input
 * where the bug is invisible. Children are now kept only if they fall under the
 * named subtree.
 *
 * ONE KEAP CALL PER INPUT ROW, capped. A chain that fanned out unbounded would
 * be a cheap way to make Wing hammer KEAP on a caller's behalf, so the input is
 * truncated before the loop and the cost is reported as rows examined. The cap
 * is the same shape `get` uses for its own `limit`.
 *
 * DEDUPLICATED BY ID, because two siblings in the input frequently share a
 * child, and a projection that returns the same node twice makes every
 * downstream count wrong — `rank … limit=5` would spend slots on duplicates.
 */
final class MapHandler implements CortexHandlerInterface
{
    /** Input rows visited per stage. A pipeline is not a crawler. */
    private const MAX_INPUT = 50;

    public function __construct(private readonly KeapCortexClient $keap)
    {
    }

    public function opcode(): string
    {
        return 'map';
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
                "'map' projects each item of its input and received none. An empty "
                . 'projection and an absent one are different facts.'
            );
        }

        // An input ARRIVED and was empty. That is an answer from the stage
        // before, not an absence here, so the honest reply is zero rows rather
        // than a refusal — see CortexContext::inputIsEmpty().
        if ($ctx->inputIsEmpty()) {
            return CortexStageResult::read([], 0);
        }

        $scope = '';
        foreach ($stage->operands as $o) {
            $scope = (string) ($o['id'] ?? $o['surface'] ?? '');
            if ($scope !== '') {
                break;
            }
        }
        if ($scope === '') {
            return CortexStageResult::nothingToOperateBy(
                "'map' projects through an operand and this stage carries none "
                . 'usable. Descending anywhere would ignore the projection the '
                . 'chain names.'
            );
        }

        $visited = array_slice($ctx->input, 0, self::MAX_INPUT);
        $truncated = max(0, count($ctx->input) - count($visited));
        $rows = [];
        $seen = [];
        $answered = 0;

        foreach ($visited as $row) {
            $id = $this->identify($row);
            if ($id === null) {
                continue;
            }
            $node = $this->keap->taxonomyNode($id);
            if ($node === null) {
                continue;
            }
            $answered++;
            foreach ((array) ($node['children'] ?? []) as $child) {
                if (!is_array($child)) {
                    continue;
                }
                $key = (string) ($child['id'] ?? $child['name'] ?? '');
                if ($key === '' || isset($seen[$key])) {
                    continue;
                }
                // Dotted-path containment, and the dot matters: without it the
                // scope `01` would also claim `010`, a different branch.
                $cid = mb_strtolower((string) ($child['id'] ?? ''));
                $prefix = mb_strtolower($scope);
                if ($cid !== $prefix && !str_starts_with($cid, $prefix . '.')) {
                    continue;
                }
                $seen[$key] = true;
                $child['ns'] = 'tax';
                $child['mappedFrom'] = $id;
                $rows[] = $child;
            }
        }

        // Every input row was unidentifiable or every fetch failed. Returning []
        // here would say "these nodes have no children", which is a claim about
        // the taxonomy rather than about the call.
        if ($answered === 0) {
            return CortexStageResult::upstreamUnreachable(sprintf(
                "'map' could not read a single one of its %d input row(s): either "
                . 'they carry no taxonomy id or KEAP did not answer. That is not '
                . 'the same as those nodes having no children.',
                count($visited)
            ));
        }

        // Say what was dropped. A cap is a defensible decision; a cap nobody is
        // told about turns 60 rows in / 25 rows out into a result that reads as
        // complete (docs/hidden_fees: "no silent caps").
        if ($truncated > 0) {
            $rows[] = [
                'ns' => 'tax',
                'note' => sprintf(
                    'input truncated: %d row(s) beyond the %d-row cap were not projected',
                    $truncated,
                    self::MAX_INPUT
                ),
                'truncated' => $truncated,
            ];
        }

        return CortexStageResult::read($rows, count($visited));
    }

    /**
     * The taxonomy id this row stands for, whatever produced it.
     *
     * `get` emits `id` and a previous `map` emits the child's `id`. `nodeId` is
     * read defensively rather than because anything produces it — CORRECTED
     * 2026-08-11: this said "`classify` emits `nodeId`", which no handler does;
     * classify attaches `classifiedAs` and leaves the row's own identity alone,
     * so `… | classify | map` descends from what went IN, not from what it was
     * assigned to. That is the honest composition; the sentence describing a
     * different one was wrong for as long as it stood.
     *
     * @param array<string,mixed> $row
     */
    private function identify(array $row): ?string
    {
        foreach (['id', 'nodeId'] as $key) {
            $v = $row[$key] ?? null;
            if (is_string($v) && $v !== '') {
                return $v;
            }
        }
        return null;
    }
}
