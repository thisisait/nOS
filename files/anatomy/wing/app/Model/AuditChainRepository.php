<?php

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;

/**
 * Reads the CACHED audit-chain integrity verdict for the Wing header badge.
 *
 * The verdict (audit_chain_meta.last_verify_ok / last_verify_at) is refreshed
 * out-of-band by the verify-audit-chain.php Pulse job (--write-verdict); this
 * repository NEVER walks the chain itself, so the per-render cost is one cheap
 * keyed SELECT. Returns known=false until the first verify job has run.
 */
final class AuditChainRepository
{
    public function __construct(private Explorer $db)
    {
    }

    /**
     * @return array{known: bool, ok: ?bool, at: ?string}
     */
    public function verdict(): array
    {
        $ok = $this->db->query("SELECT v FROM audit_chain_meta WHERE k = ?", 'last_verify_ok')->fetch();
        if ($ok === null) {
            return ['known' => false, 'ok' => null, 'at' => null];
        }
        $at = $this->db->query("SELECT v FROM audit_chain_meta WHERE k = ?", 'last_verify_at')->fetch();
        return [
            'known' => true,
            'ok' => ((string) $ok->v) === '1',
            'at' => $at !== null ? (string) $at->v : null,
        ];
    }
}
