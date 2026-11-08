<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Model\AuditChain;
use App\Model\AuditChainRepository;

/**
 * Audit hash-chain integrity — REST API (gov-readiness P1).
 *
 *   GET /api/v1/audit/verify  — cached tamper-evident-chain verdict.
 *   GET /api/v1/audit/verify 503 — the medulla serving this read has no MEDULLA_AUDIT_CHAIN: chain on or off is UNKNOWN
 *
 * Returns the CACHED verdict (audit_chain_meta, refreshed by the
 * verify-audit-chain.php Pulse job) so a web request never walks the chain.
 * chain:'off' with HTTP 200 when WING_EVENTS_HMAC_SECRET is unset (the default)
 * — never a 500 on a normal non-gov box.
 *
 * Distinct from App\Presenters\AuditPresenter (the BROWSER event drill-down);
 * this Api sub-namespace class resolves via the Api module map (Audit:verify).
 */
final class AuditPresenter extends BaseApiPresenter
{
    /** The face Anatomy Wing view shows the verdict to a Tier-1 person (row wing-inc2-agents-timeline). */
    protected array $bffOperatorReads = ['verify'];

    public function __construct(private AuditChainRepository $audit)
    {
    }

    public function actionVerify(): void
    {
        $this->requireMethod('GET');
        // Chain off (secret unset) → defined 200, mirrors the verify CLI's
        // all-unsigned exit-0. Branch FIRST so a non-gov box never errors.
        if (AuditChain::chainKey() === null) {
            $this->sendSuccess([
                'chain' => 'off',
                'ok' => true,
                'checked' => 0,
                'note' => 'WING_EVENTS_HMAC_SECRET not set — tamper-evident chain disabled',
            ]);
        }
        $v = $this->audit->verdict();
        $this->sendSuccess([
            'chain' => 'on',
            'known' => $v['known'],
            'ok' => $v['ok'],
            'verified_at' => $v['at'],
            'note' => $v['known'] ? null : 'no verdict cached yet — the verify Pulse job has not run',
        ]);
    }
}
