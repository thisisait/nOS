<?php

declare(strict_types=1);

namespace App\Cortex;

use App\Cortex\Handler\CortexHandlerInterface;
use RuntimeException;

/**
 * The closed opcode -> handler map, and the gate that refuses to boot without it.
 *
 * WHY A LITERAL MAP AND NOT A SCAN. Both design documents draw the same line and
 * it is the load-bearing one: facts about an entity may be declared in data, but
 * WHAT MAY ACT on one is code. A registry that discovered handlers by scanning a
 * directory, or read them from a manifest, would let a new capability arrive
 * without review — which is the difference between an executor and an open door.
 *
 * THE COVERAGE GATE (D3, fail-closed). KEAP publishes an opcode registry with a
 * hash. If it publishes a NON-MUTATING opcode Wing has no handler for, Wing
 * refuses to start. The ordering that follows is deliberate: Wing ships the
 * handler first, KEAP enables the opcode second. The reverse order takes the
 * estate down, which is the correct incentive.
 *
 * Mutating opcodes are excluded from coverage on purpose. KEAP publishes 14, of
 * which 7 mutate; the executor rejects every mutating stage at the door in P1,
 * so it never accepts an AST it cannot dispatch. Requiring handlers for verbs it
 * refuses to run would be a gate demanding dead code.
 */
final class CortexOpcodeRegistry
{
    /** @var array<string,CortexHandlerInterface> */
    private array $handlers = [];

    /** @param iterable<CortexHandlerInterface> $handlers */
    public function __construct(iterable $handlers)
    {
        foreach ($handlers as $h) {
            $this->handlers[$h->opcode()] = $h;
        }
    }

    public function has(string $opcode): bool
    {
        return isset($this->handlers[$opcode]);
    }

    public function handler(string $opcode): CortexHandlerInterface
    {
        if (!isset($this->handlers[$opcode])) {
            // Reached only if a caller skipped has(); the presenter answers 501
            // before this can fire. Kept loud rather than returning null.
            throw new RuntimeException("no handler for opcode '{$opcode}'");
        }
        return $this->handlers[$opcode];
    }

    /** @return list<string> */
    public function opcodes(): array
    {
        $names = array_keys($this->handlers);
        sort($names);
        return $names;
    }

    /**
     * Refuse to serve when KEAP publishes a dispatchable opcode we cannot dispatch.
     *
     * @param list<array<string,mixed>> $published KEAP's /agent/v1/validate/opcodes payload
     */
    public function assertCoversPublished(array $published): void
    {
        $missing = [];
        foreach ($published as $op) {
            $name = (string) ($op['name'] ?? '');
            if ($name === '' || ($op['mutating'] ?? false)) {
                continue;
            }
            if (!isset($this->handlers[$name])) {
                $missing[] = $name;
            }
        }
        if ($missing !== []) {
            throw new RuntimeException(
                'cortex executor cannot dispatch published non-mutating opcode(s): '
                . implode(', ', $missing)
                . '. Ship the handler in Wing BEFORE enabling the opcode in KEAP — '
                . 'this order exists so the gap fails here rather than at a caller.'
            );
        }
    }
}
