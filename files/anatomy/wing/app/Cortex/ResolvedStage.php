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

    /**
     * A parameter's VALUE, unwrapped.
     *
     * MEASURED 2026-08-11, and it had been silently wrong since the first
     * handler shipped. `cortex-lang.ts` emits each param as an object —
     * `{value, defaulted, span}` — because the span is what an error message
     * points at. Handlers read `$this->params['limit']` and cast it:
     *
     *     $limit = (int) ($stage->params['limit'] ?? 20);
     *
     * `(int)` of a non-empty PHP array is **1**. So every `limit=` ever written
     * in a chain meant one row, `threshold=70` meant 1, and nothing failed —
     * `get(tax:01, limit=50)` returned a single row and looked like a node with
     * one child. A cast that cannot fail over a shape nobody checked.
     *
     * One accessor, so the unwrapping is done once and no handler re-derives it.
     * A flat scalar is tolerated because the tests construct stages by hand.
     */
    public function param(string $key, mixed $default = null): mixed
    {
        $raw = $this->params[$key] ?? null;
        if ($raw === null) {
            return $default;
        }
        if (is_array($raw)) {
            return array_key_exists('value', $raw) ? $raw['value'] : $default;
        }
        return $raw;
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
