<?php

declare(strict_types=1);

namespace App\Cortex;

/**
 * The freshness and identity gate on a validated AST's binding block.
 *
 * KEAP stamps every valid AST with what it was validated AGAINST — measured:
 *
 *     ontologyVersion     onto1:2bf0399f0bb9f4c0
 *     databaseId          744d555f-3798-4302-af7e-cca39e165178
 *     opcodeRegistryHash  cx1:eef6024c1bdbe015
 *     validatedAt / expiresAt / ttlSeconds
 *
 * `databaseId` drift is IDENTITY drift, not staleness: the same program
 * validated against a different KEAP database means the ids in it point at
 * different things. That is a 409 and never a silent re-resolve, because
 * re-resolving would quietly execute against a world the caller never saw.
 *
 * The executor revalidates on every dispatch, so the binding it checks is
 * seconds old. A caller may pass its own cached binding to prove it is looking
 * at the same world; a mismatch is refused rather than tolerated. What a caller
 * may never pass is an AST — proving freshness and supplying the program to run
 * are different powers, and only the first is delegated.
 */
final class CortexBindingGate
{
    public const DRIFT = 'binding_drift';
    public const EXPIRED = 'binding_expired';

    /**
     * @param array<string,mixed>      $fresh  binding from the just-validated AST
     * @param array<string,mixed>|null $cached binding the caller claims to hold
     * @return array{code:string,detail:string}|null null = dispatchable
     */
    public function check(array $fresh, ?array $cached): ?array
    {
        $expiresAt = (string) ($fresh['expiresAt'] ?? '');
        if ($expiresAt !== '' && strtotime($expiresAt) !== false && strtotime($expiresAt) < time()) {
            // Should be unreachable — we validated moments ago — so if it fires,
            // KEAP's clock and ours disagree, which is worth saying out loud
            // rather than dispatching against a binding already dead.
            return ['code' => self::EXPIRED,
                    'detail' => "the binding KEAP just issued expired at {$expiresAt}; "
                        . 'check clock skew between Wing and the KEAP container'];
        }
        if ($cached === null) {
            return null;
        }
        foreach (['databaseId', 'ontologyVersion', 'opcodeRegistryHash'] as $field) {
            $a = (string) ($fresh[$field] ?? '');
            $b = (string) ($cached[$field] ?? '');
            if ($b !== '' && $a !== $b) {
                return ['code' => self::DRIFT,
                        'detail' => "{$field} moved since you validated: you hold "
                            . "'{$b}', KEAP now reports '{$a}'. Re-validate — the "
                            . 'ids in your program may not mean what they did.'];
            }
        }
        return null;
    }
}
