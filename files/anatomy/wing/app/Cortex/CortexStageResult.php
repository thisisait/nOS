<?php

declare(strict_types=1);

namespace App\Cortex;

/**
 * What one dispatched stage produced.
 *
 * `effect` is 'read' for every P1 verb and is carried explicitly rather than
 * inferred, so the day a write verb lands the audit row says which it was
 * without anyone re-deriving it from the opcode name.
 *
 * `code` is set only when the handler could not do its job for a reason that is
 * NOT an error — a typed absence. P1 uses one: `late_binding_unavailable`, for
 * verbs whose upstream read surface KEAP does not publish yet. A stage that
 * returns it is honest about having done nothing; a stage that returned empty
 * rows would look like a successful query over an empty world.
 */
final class CortexStageResult
{
    /** @param list<array<string,mixed>> $rows */
    private function __construct(
        public readonly string $effect,
        public readonly array $rows,
        public readonly int $cost,
        public readonly ?string $code = null,
        public readonly ?string $detail = null,
    ) {
    }

    /** @param list<array<string,mixed>> $rows */
    public static function read(array $rows, int $cost = 0): self
    {
        return new self('read', $rows, $cost);
    }

    /**
     * The handler exists, the verb is legal, and the surface it would call does
     * not exist yet. Deliberately NOT an error: the D3 coverage gate requires a
     * handler for every published non-mutating opcode, and a typed absence is
     * how a handler can be present and honest at the same time.
     *
     * ONLY for a genuinely absent upstream. After 2026-08-11 that is `embed`
     * alone; see the three constructors below for the reasons this code used to
     * be borrowed for.
     */
    public static function unavailable(string $detail): self
    {
        return new self('read', [], 0, 'late_binding_unavailable', $detail);
    }

    /**
     * An earlier stage produced nothing to operate on.
     *
     * SPLIT OUT 2026-08-11, hours after the pipe first piped. Every absence
     * above and below was reported as `late_binding_unavailable`, so one label
     * covered "this verb has no upstream", "your chain matched nothing" and
     * "KEAP is down". Any consumer counting late-bound verbs over-counted; more
     * expensively, the queued RFL corpus and intent grader would have trained on
     * a signal that cannot separate a bad chain from an outage — and relabelling
     * a generated corpus costs more than four constructors.
     */
    public static function pipeBroken(string $detail): self
    {
        return new self('read', [], 0, 'pipe_broken', $detail);
    }

    /**
     * The stage ran, and the caller gave it nothing to work BY — no predicate,
     * no signal, no operand. A caller error, not an estate condition.
     */
    public static function nothingToOperateBy(string $detail): self
    {
        return new self('read', [], 0, 'nothing_to_operate_by', $detail);
    }

    /**
     * The surface exists and did not answer. Distinct from every code above
     * because it is the only one that will be different tomorrow without anyone
     * changing anything, and the only one an operator should be paged about.
     */
    public static function upstreamUnreachable(string $detail): self
    {
        return new self('read', [], 0, 'upstream_unreachable', $detail);
    }

    /** Every typed-absence code this class can produce. */
    public const ABSENCE_CODES = [
        'late_binding_unavailable',
        'pipe_broken',
        'nothing_to_operate_by',
        'upstream_unreachable',
    ];

    /** @return array<string,mixed> */
    public function toArray(): array
    {
        $out = ['effect' => $this->effect, 'rows' => $this->rows, 'cost' => $this->cost];
        if ($this->code !== null) {
            $out['code'] = $this->code;
            $out['detail'] = $this->detail;
        }
        return $out;
    }
}
