<?php
/**
 * /gdpr — GDPR Article 30 register browser view.
 *
 * Renders the processing activities + DSAR + breach summary in a single
 * page. All edit/insert flows go through the API (authentik proxy auth +
 * Wing token gates them); this presenter is read-only for now.
 *
 * Track D (2026-04-26).
 */

declare(strict_types=1);

namespace App\Presenters;

use App\Model\GdprRepository;
use App\Model\KeapCortexClient;

final class GdprPresenter extends BasePresenter
{
    /** Mirrors module_utils/nos_gdpr.py::PLATFORM_SECURITY_MEASURES verbatim —
     *  the same constant `controller_records()` falls back to when a party
     *  carries no gdpr: block of its own (every party does, by construction). */
    private const PLATFORM_SECURITY_MEASURES = [
        'TLS in transit (Traefik edge; wildcard cert)',
        'Authentik SSO + RBAC tier access control',
        'Secrets held in Infisical / launchd env, never plaintext at rest',
        'Disk encryption at rest is operator-provisioned (FileVault / LUKS)',
        'Self-hosted: no third-party data processor unless declared below',
    ];

    // The Art-30 register + DSAR log + breach register expose EVERY data
    // subject's email and request history. Gate at Tier-1 (nos-providers/
    // nos-admins) — the sibling BreachesPresenter gates the same breach data at
    // tier 1, and DSAR-intake rows land straight into this view. Without this,
    // $minAccessTier defaults null -> no RBAC gate -> tier-4 guests could read it.
    //
    // clientRecords is the ONE exception (D5 art30-live-view): the epic's other
    // tables (pending-invoice-verify, invoice, account) are tier-managers, and a
    // consultant seat that can approve an invoice but 403s on the client's own
    // Art-30 record would be a gap, not a tightening. startup() below drops the
    // gate to tier-managers for exactly that one action.
    protected ?int $minAccessTier = 1;

    protected string $activeTab = 'gdpr';

    public function __construct(
        private GdprRepository $repo,
        private KeapCortexClient $keap,
    ) {
    }

    public function startup(): void
    {
        if ($this->getAction() === 'clientRecords') {
            $this->minAccessTier = null; // suppress the class-wide tier-1 check below
        }
        parent::startup();
        if ($this->getAction() === 'clientRecords') {
            $this->requireTier(2); // tier-managers — same seat as the epic's other tables
        }
    }

    /**
     * READ-ONLY. Live-computes the ONE client's Art-30 record from its KEAP
     * party row — mirrors module_utils/nos_gdpr.py::controller_records() at
     * reduced field parity (a live view, not the committed register). Writes
     * NOTHING: no repository call, no insert, no file write — a refresh
     * recomputes from KEAP every time (D4's runtime-only rule).
     */
    public function renderClientRecords(string $partySlug): void
    {
        $party = $this->keap->tableRowBySlug('party', $partySlug);
        $this->template->partySlug = $partySlug;
        $this->template->party = $party;
        $this->template->record = $party !== null ? $this->controllerRecordFor($party) : null;
    }

    /**
     * @param array<string,mixed> $party
     * @return array<string,mixed>|null
     */
    private function controllerRecordFor(array $party): ?array
    {
        $role = $party['role'] ?? null;
        if (!in_array($role, ['client', 'own_firm'], true)) {
            return null; // counterparty / no-role parties are not GDPR-mapped, same as the Python twin
        }
        $slug = (string) ($party['slug'] ?? '');
        $name = (string) ($party['legal_name'] ?? $slug);
        return [
            'id' => 'party_' . $slug,
            'slug' => $slug,
            'name' => $name,
            'art30_role' => $role === 'own_firm' ? 'controller' : 'processor',
            'purpose' => sprintf(
                'Operation of the %s service within the nOS self-hosted platform; '
                . 'processing limited to what the service requires to function for authenticated users.',
                $name
            ),
            'legal_basis' => '',
            'data_categories' => [],
            'data_subjects' => [],
            'processors' => [],
            'security_measures' => self::PLATFORM_SECURITY_MEASURES,
            'retention_days' => null,
            'transfers_outside_eu' => false,
            'storage_location' => 'host service (non-Docker / launchd)',
            'eu_residency' => true,
            'tier' => 'party',
            'source_plugin' => 'party:' . $slug,
        ];
    }

    public function renderDefault(): void
    {
        $processing = $this->repo->listProcessing();
        $dsar = $this->repo->listDsar();
        $breaches = $this->repo->listBreaches();

        $stats = [
            'processingCount' => count($processing),
            'pendingDsar' => count(array_filter(
                $dsar,
                static fn(array $r) => in_array($r['status'] ?? '', ['received', 'in-progress'], true)
            )),
            'completedDsar' => count(array_filter(
                $dsar,
                static fn(array $r) => ($r['status'] ?? '') === 'completed'
            )),
            'openBreaches' => count(array_filter(
                $breaches,
                static fn(array $r) => in_array($r['status'] ?? '', ['detected', 'notified'], true)
            )),
        ];

        $this->template->processing = $processing;
        $this->template->dsar = $dsar;
        $this->template->breaches = $breaches;
        $this->template->stats = $stats;
    }
}
