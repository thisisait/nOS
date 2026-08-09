<?php

declare(strict_types=1);

namespace App\Cortex;

/**
 * What one token may execute: verbs x namespaces x tenants.
 *
 * THE RULE THE DESIGN CALLS NON-NEGOTIABLE — "the strong token may not use the
 * weak door." Wing's flat brain token authenticates every other API route; if
 * it also opened the executor, the capability model would be decoration, since
 * anyone holding the brain token could run any verb over any namespace. So a
 * token with no cortex axes is REFUSED here, and being powerful elsewhere is
 * not a way in.
 *
 * That is also why the three columns default to NULL: every token that existed
 * before this shipped has no cortex capability, and someone has to say, per
 * token and per axis, what it may do.
 *
 * Namespaces are matched as written, so `db:wing` and `db:gdpr` are different
 * grants — a bare `db` would let a token that may read events also read the
 * GDPR store, which is exactly the collapse the qualified form prevents.
 */
final class CortexCapability
{
    /**
     * @param list<string> $verbs
     * @param list<string> $namespaces
     * @param list<string> $tenants
     */
    private function __construct(
        public readonly array $verbs,
        public readonly array $namespaces,
        public readonly array $tenants,
    ) {
    }

    /** @param array<string,mixed>|null $tokenRow */
    public static function fromToken(?array $tokenRow): ?self
    {
        if ($tokenRow === null) {
            return null;
        }
        $split = static function (mixed $v): array {
            if (!is_string($v) || trim($v) === '') {
                return [];
            }
            return array_values(array_filter(array_map('trim', explode(',', $v)), static fn($s) => $s !== ''));
        };
        $verbs = $split($tokenRow['cortex_verbs'] ?? null);
        $ns = $split($tokenRow['cortex_namespaces'] ?? null);
        $tenants = $split($tokenRow['cortex_tenants'] ?? null);

        // All three axes must be granted. A token with verbs but no namespaces
        // is a half-written grant, and guessing which half was meant is how a
        // capability quietly becomes wider than anyone intended.
        if ($verbs === [] || $ns === [] || $tenants === []) {
            return null;
        }
        return new self($verbs, $ns, $tenants);
    }

    public function allowsVerb(string $opcode): bool
    {
        return in_array('*', $this->verbs, true) || in_array($opcode, $this->verbs, true);
    }

    /**
     * A namespace grant matches exactly, or as a qualified prefix: `db:wing`
     * covers `db:wing` and nothing else, while a bare `db` covers `db` and
     * `db:<anything>`. Writing the bare form is therefore a deliberate widening.
     */
    public function allowsNamespace(string $ns): bool
    {
        if (in_array('*', $this->namespaces, true)) {
            return true;
        }
        foreach ($this->namespaces as $grant) {
            if ($grant === $ns || str_starts_with($ns, $grant . ':')) {
                return true;
            }
        }
        return false;
    }

    public function allowsTenant(string $tenant): bool
    {
        return in_array('*', $this->tenants, true) || in_array($tenant, $this->tenants, true);
    }
}
