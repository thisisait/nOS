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
 * CORRECTED 2026-08-10. This header used to record that `/agent/v1/taxonomy`,
 * `/nodes` and `/search` all answer 401 and conclude that KEAP publishes no
 * node fetch. The 401s were real; the conclusion was not. Re-probed against the
 * running KEAP (127.0.0.1:8091, RO bearer):
 *
 *     /agent/v1/relations              200
 *     /agent/v1/objects                200
 *     /agent/v1/taxonomy/node/:id      200   <- the node fetch, all along
 *     /agent/v1/taxonomy/search        200
 *     /agent/v1/search/semantic        200
 *     /agent/v1/taxonomy               401   (no route at that exact path)
 *
 * The first probe tested the paths the DESIGN DOCUMENT named (docs/archive/nos-cortex-lang-wing-executor.md §3.4's table)
 * instead of the ones KEAP serves, and a 401 from the forward-auth catch-all on
 * an unrouted path is indistinguishable from a scope refusal — which is how a
 * measurement that was carefully performed still reached a false conclusion.
 *
 * So `rel:` is served from `relations` and `tax:` now really is fetched. When
 * KEAP does not answer, the AST's own resolution is returned AND LABELLED as a
 * fallback, because an unreachable upstream must not read like a node with no
 * children.
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
            // tax: KEAP DOES publish a node fetch — `/agent/v1/taxonomy/node/:id`,
            // 200 to the RO bearer, carrying children/ancestors/childCount/
            // curated/contentLink. The comment that used to stand here said the
            // opposite and was wrong: the probe behind it tested the design
            // document's paths rather than KEAP's surface (see
            // KeapCortexClient::taxonomyNode).
            $node = $this->keap->taxonomyNode((string) ($o['id'] ?? $o['surface'] ?? ''));
            if ($node === null) {
                // Fall back to what the AST already carries, and SAY that it is
                // a fallback. An unreachable KEAP must not read like a node with
                // no children.
                $rows[] = [
                    'ns' => $ns,
                    'id' => $o['id'] ?? null,
                    'resolvedName' => $o['resolvedName'] ?? null,
                    'note' => 'resolution only — KEAP node fetch did not answer',
                ];
                continue;
            }
            $node['ns'] = $ns;
            $rows[] = $node;
        }
        return CortexStageResult::read(array_slice($rows, 0, $limit), count($rows));
    }
}
