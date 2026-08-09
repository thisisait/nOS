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
     */
    public static function unavailable(string $detail): self
    {
        return new self('read', [], 0, 'late_binding_unavailable', $detail);
    }

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
