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
        if (!$ctx->hasInput()) {
            return CortexStageResult::unavailable(
                "'map' projects each item of its input and received none. An empty "
                . 'projection and an absent one are different facts.'
            );
        }

        $visited = array_slice($ctx->input, 0, self::MAX_INPUT);
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
            return CortexStageResult::unavailable(sprintf(
                "'map' could not read a single one of its %d input row(s): either "
                . 'they carry no taxonomy id or KEAP did not answer. That is not '
                . 'the same as those nodes having no children.',
                count($visited)
            ));
        }

        return CortexStageResult::read($rows, count($visited));
    }

    /**
     * The taxonomy id this row stands for, whatever produced it.
     *
     * `get` emits `id`, a previous `map` emits the child's `id`, `classify`
     * emits `nodeId`. Reading one key would make the verb composable after one
     * predecessor and silently inert after another.
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
