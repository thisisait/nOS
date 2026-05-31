<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Pure GDPR Art-33/34 + NIS2/ZKB (NÚKIB) breach-notification deadline math.
 *
 * No DB, no I/O, no clock side-effects beyond the $now passed into
 * overdueStages(). Every timestamp is normalized to a true UTC instant BEFORE
 * the interval add (an offset-bearing input like '...+05:00' is CONVERTED, not
 * preserved — closes the silent host-offset skew).
 *
 * Deadlines (breach-notification engine, gov P1, 2026-05-31):
 *   Art-33  supervisory authority (CZ: ÚOOÚ) = aware_at + 72h, ONLY when
 *           risk_level != none AND status != non-reportable (Art-33(1)).
 *   Art-34  data subjects ('without undue delay') = aware_at marker, ONLY when
 *           risk_level == high AND no Art-34(3) exception. REPORT-ONLY — the
 *           scanner NEVER escalates it (no zero-hour deadline -> no t=0 spam).
 *   NIS2/ZKB (NÚKIB) gated on nis2_in_scope, anchored on detected_at:
 *           +24h early warning, +72h notification, +1 month (end-of-month
 *           clamped) final report.
 */
final class BreachDeadlines
{
    public const ART33_HOURS = 72;       // GDPR supervisory authority (ÚOOÚ)
    public const NIS2_EARLY_HOURS = 24;  // NÚKIB early warning (varování)
    public const NIS2_NOTIFY_HOURS = 72; // NÚKIB notification (distinct from GDPR 72h)

    /** Stages the scan may ESCALATE. Art-34 is deliberately ABSENT (report-only). */
    public const ESCALATING_STAGES = ['art33', 'nis2_24h', 'nis2_72h', 'nis2_final'];

    /** Convert any ISO-8601 string to a true UTC instant (offset is applied, not kept). */
    private static function utc(string $ts): \DateTimeImmutable
    {
        return (new \DateTimeImmutable($ts))->setTimezone(new \DateTimeZone('UTC'));
    }

    /** $base + N months, clamped to the last day of the target month (no P1M overflow). */
    private static function addMonthsClamped(\DateTimeImmutable $base, int $months): \DateTimeImmutable
    {
        $day = (int) $base->format('j');
        $firstOfTarget = $base->modify('first day of this month')->modify("+{$months} month");
        $lastDay = (int) $firstOfTarget->format('t');
        return $firstOfTarget->setDate(
            (int) $firstOfTarget->format('Y'),
            (int) $firstOfTarget->format('n'),
            min($day, $lastDay)
        );
    }

    /**
     * Compute all stage deadlines for a breach row.
     *
     * @param array<string,mixed> $b
     * @return array<string,array{applicable:bool,due_at:?string,done_at:?string}>
     */
    public static function compute(array $b): array
    {
        $aware = self::utc((string) ($b['aware_at'] ?? $b['detected_at']));
        $detected = self::utc((string) $b['detected_at']);
        $risk = (string) ($b['risk_level'] ?? 'none');

        $reportable = $risk !== 'none' && ($b['status'] ?? '') !== 'non-reportable'; // Art-33(1)
        $highRisk = $risk === 'high';
        $art34Waived = !empty($b['art34_exception']);                                 // Art-34(3)
        $nis2 = (int) ($b['nis2_in_scope'] ?? 0) === 1;

        return [
            'art33' => [
                'applicable' => $reportable,
                'due_at' => $reportable
                    ? $aware->add(new \DateInterval('PT' . self::ART33_HOURS . 'H'))->format('c')
                    : null,
                'done_at' => $b['notified_supervisor_at'] ?? null,
            ],
            // Art-34 is REPORT-ONLY ('without undue delay'); due_at == aware_at is
            // a reporting marker only — the scanner does NOT escalate this stage.
            'art34' => [
                'applicable' => $highRisk && !$art34Waived,
                'due_at' => ($highRisk && !$art34Waived) ? $aware->format('c') : null,
                'done_at' => $b['notified_subjects_at'] ?? null,
            ],
            'nis2_24h' => [
                'applicable' => $nis2,
                'due_at' => $nis2
                    ? $detected->add(new \DateInterval('PT' . self::NIS2_EARLY_HOURS . 'H'))->format('c')
                    : null,
                'done_at' => $b['nis2_early_warning_done_at'] ?? null,
            ],
            'nis2_72h' => [
                'applicable' => $nis2,
                'due_at' => $nis2
                    ? $detected->add(new \DateInterval('PT' . self::NIS2_NOTIFY_HOURS . 'H'))->format('c')
                    : null,
                'done_at' => $b['nis2_notification_done_at'] ?? null,
            ],
            'nis2_final' => [
                'applicable' => $nis2,
                'due_at' => $nis2 ? self::addMonthsClamped($detected, 1)->format('c') : null,
                'done_at' => $b['nis2_final_report_done_at'] ?? null,
            ],
        ];
    }

    /**
     * Escalating stages that are overdue: applicable AND due_at past AND not done.
     * Art-34 is intentionally EXCLUDED. $now = ISO-8601 (UTC-normalized) or null.
     *
     * @param array<string,mixed> $b
     * @return list<string>
     */
    public static function overdueStages(array $b, ?string $now = null): array
    {
        $nowT = $now !== null ? self::utc($now) : new \DateTimeImmutable('now', new \DateTimeZone('UTC'));
        $computed = self::compute($b);
        $out = [];
        foreach (self::ESCALATING_STAGES as $stage) {
            $d = $computed[$stage];
            if ($d['applicable'] && $d['due_at'] !== null && empty($d['done_at'])
                && self::utc($d['due_at']) < $nowT) {
                $out[] = $stage;
            }
        }
        return $out;
    }
}
