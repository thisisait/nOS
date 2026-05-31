<?php

declare(strict_types=1);

namespace App\Presenters;

use App\Model\BreachDeadlines;
use App\Model\GdprRepository;

/**
 * Tier-1 READ-ONLY view of the GDPR Art-33/34 + NÚKIB breach register with
 * per-stage deadline countdowns (gov-readiness P1 demo surface).
 *
 * Filing + stage-discharge run through bin/breach-file.php + the engine
 * (GdprRepository::markStage); a browser filing form is a deferred follow-up.
 * Tier-1 gated declaratively via $minAccessTier (BasePresenter::startup) — same
 * boundary as the forward-auth tier-1 edge on wing.<tld>.
 */
final class BreachesPresenter extends BasePresenter
{
    protected string $activeTab = 'breaches';
    protected ?int $minAccessTier = 1;

    public function __construct(private GdprRepository $repo)
    {
    }

    public function renderDefault(): void
    {
        $rows = [];
        foreach ($this->repo->listBreaches() as $b) {
            $rows[] = ['b' => $b, 'deadlines' => BreachDeadlines::compute($b)];
        }
        $this->template->breaches = $rows;
    }

    public function renderDetail(int $id): void
    {
        $b = $this->repo->getBreach($id);
        if ($b === null) {
            $this->error('breach not found');
        }
        $this->template->breach = $b;
        $this->template->deadlines = BreachDeadlines::compute($b);
    }
}
