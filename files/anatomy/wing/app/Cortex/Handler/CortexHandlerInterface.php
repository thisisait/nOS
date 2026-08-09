<?php

declare(strict_types=1);

namespace App\Cortex\Handler;

use App\Cortex\CortexContext;
use App\Cortex\CortexStageResult;
use App\Cortex\ResolvedStage;

/**
 * One verb, one class.
 *
 * Shaped to read like AgentKit's ToolInterface (opcode ≈ identifier, execute ≈
 * run) so the two runtimes feel the same, but thinner on purpose: no scopes
 * plumbing, because scope was decided at the door.
 *
 * THE RULE THAT MAY NOT BE RELAXED. A capability is CODE. `CortexOpcodeRegistry`
 * holds a closed literal map from opcode to class; nothing reads a manifest, a
 * table or an env var to learn about a new verb. Both cortex-lang's own design
 * and the Wing executor design state it independently: a capability must not be
 * addable by data. Handlers may be thin, but they must exist and be reviewed.
 */
interface CortexHandlerInterface
{
    public function opcode(): string;

    /** False for every P1 verb. Wing re-derives it and never trusts the AST flag alone. */
    public function mutating(): bool;

    /**
     * Namespaces this handler accepts, which MUST be a subset of what KEAP
     * accepts for the same opcode. Narrower is safe; wider is a way to reach a
     * surface KEAP never agreed to.
     *
     * @return list<string>
     */
    public function acceptedNamespaces(): array;

    public function execute(ResolvedStage $stage, CortexContext $ctx): CortexStageResult;
}
