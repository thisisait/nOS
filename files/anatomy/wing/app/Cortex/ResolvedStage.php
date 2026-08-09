<?php

declare(strict_types=1);

namespace App\Cortex;

/**
 * One stage of a validated pipeline, as a handler receives it.
 *
 * Built from KEAP's AST, never from the request body. The executor re-POSTs the
 * source to KEAP on every dispatch and reads the stages off the fresh report —
 * a caller may pass a cached `ast_binding` to prove freshness, never an AST to
 * be executed. Accepting a caller-supplied AST would let anyone hand us a
 * program KEAP never agreed to.
 *
 * Operands arrive already resolved for the `tax` and `rel` namespaces: KEAP
 * fills in `id` and `resolvedName` at validate time (measured — `tax:01`
 * carries `{"id":"01","resolvedName":"Natural Sciences"}`). That is what makes
 * `resolve` a pure read-back with no downstream I/O.
 */
final class ResolvedStage
{
    /**
     * @param list<array<string,mixed>> $operands
     * @param array<string,mixed>       $params
     */
    public function __construct(
        public readonly int $index,
        public readonly string $opcode,
        public readonly bool $mutating,
        public readonly array $operands,
        public readonly array $params,
    ) {
    }

    /** @param array<string,mixed> $stage */
    public static function fromAst(array $stage): self
    {
        return new self(
            (int) ($stage['index'] ?? 0),
            (string) ($stage['opcode'] ?? ''),
            (bool) ($stage['mutating'] ?? false),
            array_values((array) ($stage['operands'] ?? [])),
            (array) ($stage['params'] ?? []),
        );
    }

    /** Namespaces this stage's operands reach. */
    public function namespaces(): array
    {
        $ns = [];
        foreach ($this->operands as $o) {
            if (isset($o['ns']) && is_string($o['ns'])) {
                $ns[$o['ns']] = true;
            }
        }
        return array_keys($ns);
    }
}
