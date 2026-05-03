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

final class GdprPresenter extends BasePresenter
{
    protected string $activeTab = 'gdpr';

    public function __construct(
        private GdprRepository $repo,
    ) {
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
