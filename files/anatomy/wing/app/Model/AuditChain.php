<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Tamper-evident audit hash-chain — single source of truth for the algorithm.
 *
 * Used by:
 *   - App\Model\EventRepository  (WRITER — signs each row on insert)
 *   - bin/verify-audit-chain.php (VERIFIER — recomputes + checks the chain)
 *
 * A Python mirror lives in files/anatomy/bone/clients/wing.py (Bone is the
 * other writer into wing.db). Cross-language byte-parity of canonical() is the
 * load-bearing invariant and is pinned by tests/anatomy/test_audit_chain.py.
 *
 * THREAT MODEL: tamper-EVIDENT, not tamper-PROOF. The chain key derives from
 * the on-box WING_EVENTS_HMAC_SECRET. An attacker who can both write wing.db
 * AND read that secret can recompute the whole chain undetectably. The control
 * detects DB-only tampering (a row edited/deleted/reordered without re-signing
 * the suffix). Off-box key custody + periodic off-host head anchoring would
 * raise the bar — tracked as a follow-up.
 */
final class AuditChain
{
    public const CHAIN_LABEL = 'wing-events-chain-v1';
    public const GENESIS = 'nos-audit-chain-genesis-v1';

    /**
     * The 18 immutable columns, PINNED ORDER, that form the hashed payload.
     * actor_action_id is EXCLUDED — the two AgentSessionRepository back-stamps
     * legitimately UPDATE it after insert, so it must not be covered by the
     * row hash. id / created_at / prev_hash / row_hash are EXCLUDED too
     * (db-assigned or chain-derived).
     *
     * @var string[]
     */
    public const CANON_FIELDS = [
        'ts', 'run_id', 'type', 'playbook', 'play', 'task', 'role', 'host',
        'duration_ms', 'changed', 'result_json', 'migration_id', 'upgrade_id',
        'patch_id', 'coexist_svc', 'source', 'actor_id', 'acted_at',
    ];

    /**
     * Derive the chain key from WING_EVENTS_HMAC_SECRET. Returns null when the
     * secret is unset — callers then take the unsigned (chain-off) path.
     */
    public static function chainKey(): ?string
    {
        $s = (string) (getenv('WING_EVENTS_HMAC_SECRET') ?: '');
        return $s === '' ? null : hash_hmac('sha256', self::CHAIN_LABEL, $s);
    }

    /**
     * Canonical JSON of the immutable fields: compact, slashes + unicode
     * unescaped — byte-identical to Python
     * json.dumps(map, separators=(',', ':'), ensure_ascii=False).
     *
     * @param array<string,mixed> $row
     */
    public static function canonical(array $row): string
    {
        $map = [];
        foreach (self::CANON_FIELDS as $f) {
            $map[$f] = array_key_exists($f, $row) ? $row[$f] : null;
        }
        return json_encode($map, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    }

    /**
     * row_hash = HMAC-SHA256(chainKey, prev_hash . canonical(row)).
     *
     * @param array<string,mixed> $row
     */
    public static function rowHash(string $prev, array $row, string $key): string
    {
        return hash_hmac('sha256', $prev . self::canonical($row), $key);
    }
}
