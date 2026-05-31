<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Pure GDPR Art-33/34 + NÚKIB/ZKB regulator-report assembly. No I/O — shared by
 * bin/breach-report.php (CLI) and Api\GdprPresenter::actionBreachReport so the
 * CLI export and the web API can never drift. Controller identity is read from
 * the GDPR_* env (blank fallback on a non-gov host).
 */
final class BreachReport
{
    /**
     * @param array<string, mixed> $b a gdpr_breaches row
     * @return array<string, mixed>
     */
    public static function build(array $b): array
    {
        $id = (int) ($b['id'] ?? 0);
        $d = BreachDeadlines::compute($b);
        $overdue = static fn(?string $due, ?string $doneAt): bool =>
            empty($doneAt) && $due !== null && strtotime($due) < time();

        return [
            'breach_id' => $id,
            'controller' => [
                'name' => getenv('GDPR_CONTROLLER_NAME') ?: '',
                'dpo_name' => getenv('GDPR_DPO_NAME') ?: '',
                'dpo_contact' => getenv('GDPR_DPO_CONTACT') ?: '',
            ],
            // Art-33(3)(a)-(d) — to ÚOOÚ.
            'art33' => $d['art33']['applicable'] ? [
                'nature' => $b['nature'],
                'data_categories' => $b['data_categories'] ?? null,
                'affected_subjects' => $b['affected_subjects'] ?? null,
                'affected_records' => $b['affected_records'] ?? null,
                'consequences' => $b['likely_consequences'] ?? null,
                'measures' => $b['measures_taken'] ?? null,
                'risk_level' => $b['risk_level'],
                'detected_at' => $b['detected_at'],
                'aware_at' => $b['aware_at'] ?? $b['detected_at'],
                'due_at' => $d['art33']['due_at'],
                'notified_at' => $b['notified_supervisor_at'] ?? null,
                'overdue' => $overdue($d['art33']['due_at'], $b['notified_supervisor_at'] ?? null),
            ] : ['skipped_reason' => 'not reportable (risk_level=none or status=non-reportable)'],
            // Art-34 — 33(3) b,c,d only (NOT a). Report-only; no escalation.
            'art34' => $d['art34']['applicable'] ? [
                'nature_plain' => $b['nature'],
                'consequences' => $b['likely_consequences'] ?? null,
                'measures' => $b['measures_taken'] ?? null,
                'notified_at' => $b['notified_subjects_at'] ?? null,
            ] : [
                'skipped_reason' => ($b['risk_level'] === 'high'
                    ? 'Art-34(3) exception: ' . ($b['art34_exception'] ?? '')
                    : 'not high risk'),
            ],
            // NÚKIB / ZKB — separate track, anchored on detected_at.
            'nukib' => (int) ($b['nis2_in_scope'] ?? 0) ? [
                'regime' => $b['nis2_regime'] ?? null,
                'authority' => (($b['nis2_regime'] ?? '') === 'lower' ? 'National CERT' : 'NÚKIB'),
                'cross_border' => (bool) ($b['nis2_cross_border'] ?? 0),
                'intentional_suspected' => (bool) ($b['nis2_intentional_suspected'] ?? 0),
                'early_warning_24h' => ['due' => $d['nis2_24h']['due_at'], 'done' => $b['nis2_early_warning_done_at'] ?? null],
                'notification_72h' => ['due' => $d['nis2_72h']['due_at'], 'done' => $b['nis2_notification_done_at'] ?? null],
                'final_report_30d' => ['due' => $d['nis2_final']['due_at'], 'done' => $b['nis2_final_report_done_at'] ?? null],
            ] : null,
        ];
    }

    /**
     * @param array<string, mixed> $report output of build()
     */
    public static function renderMarkdown(array $report): string
    {
        $id = $report['breach_id'];
        $nv = static fn($v): string => ($v === null || $v === '') ? '_(unset)_' : (string) $v;
        $lines = [];
        $lines[] = "# GDPR Breach Report — #{$id}";
        $lines[] = "";
        $lines[] = "**Controller:** " . $nv($report['controller']['name']) . "  ";
        $lines[] = "**DPO:** " . $nv($report['controller']['dpo_name']) . " — " . $nv($report['controller']['dpo_contact']);
        $lines[] = "";
        $lines[] = "## Art-33 — supervisory authority (ÚOOÚ)";
        if (isset($report['art33']['skipped_reason'])) {
            $lines[] = "Skipped: {$report['art33']['skipped_reason']}";
        } else {
            $a = $report['art33'];
            $lines[] = "- (a) Nature: " . $nv($a['nature']) . "; categories " . $nv($a['data_categories'])
                     . "; ~" . $nv($a['affected_subjects']) . " subjects / " . $nv($a['affected_records']) . " records";
            $lines[] = "- (b) DPO contact: see header";
            $lines[] = "- (c) Likely consequences: " . $nv($a['consequences']);
            $lines[] = "- (d) Measures taken: " . $nv($a['measures']);
            $lines[] = "- Aware at " . $nv($a['aware_at']) . "; **72h due " . $nv($a['due_at']) . "**; notified "
                     . $nv($a['notified_at']) . ($a['overdue'] ? " — **OVERDUE**" : "");
        }
        $lines[] = "";
        $lines[] = "## Art-34 — data subjects";
        if (isset($report['art34']['skipped_reason'])) {
            $lines[] = "Skipped: {$report['art34']['skipped_reason']}";
        } else {
            $lines[] = "- Plain-language nature: " . $nv($report['art34']['nature_plain']);
            $lines[] = "- Consequences: " . $nv($report['art34']['consequences']);
            $lines[] = "- Measures: " . $nv($report['art34']['measures']);
            $lines[] = "- Notified subjects at: " . $nv($report['art34']['notified_at']) . " (without undue delay)";
        }
        $lines[] = "";
        $lines[] = "## NÚKIB / ZKB";
        if ($report['nukib'] === null) {
            $lines[] = "Not in NIS2/ZKB scope.";
        } else {
            $n = $report['nukib'];
            $lines[] = "- Authority: {$n['authority']} (regime " . $nv($n['regime']) . "); cross-border "
                     . ($n['cross_border'] ? 'yes' : 'no') . "; intentional-suspected "
                     . ($n['intentional_suspected'] ? 'yes' : 'no');
            $lines[] = "- 24h early warning: due " . $nv($n['early_warning_24h']['due']) . ", done " . $nv($n['early_warning_24h']['done']);
            $lines[] = "- 72h notification: due " . $nv($n['notification_72h']['due']) . ", done " . $nv($n['notification_72h']['done']);
            $lines[] = "- 30d final report: due " . $nv($n['final_report_30d']['due']) . ", done " . $nv($n['final_report_30d']['done']);
        }
        return implode("\n", $lines) . "\n";
    }
}
