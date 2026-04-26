<?php
/**
 * GDPR Article 30 register — repository.
 *
 * Wraps SQLite reads/writes for the gdpr_processing, gdpr_dsar and
 * gdpr_breaches tables (defined in db/schema-extensions.sql, seeded by
 * db/gdpr-seed.sql). All JSON columns are auto-decoded on read and
 * encoded on write so callers see plain PHP arrays.
 *
 * Track D (2026-04-26).
 */

declare(strict_types=1);

namespace App\Model;

use Nette\Database\Explorer;
use Nette\Database\Table\ActiveRow;

final class GdprRepository
{
    /** @var list<string> */
    private const PROCESSING_JSON_COLS = ['data_categories', 'data_subjects', 'processors', 'security_measures'];
    /** @var list<string> */
    private const DSAR_JSON_COLS = ['processing_ids'];

    public function __construct(private Explorer $db) {}

    // ── Processing register (Art. 30) ────────────────────────────────────

    /** @return list<array<string, mixed>> */
    public function listProcessing(): array
    {
        return array_map(
            fn(ActiveRow $r) => $this->decodeRow($r->toArray(), self::PROCESSING_JSON_COLS),
            iterator_to_array($this->db->table('gdpr_processing')->order('id ASC'))
        );
    }

    public function getProcessing(string $id): ?array
    {
        $row = $this->db->table('gdpr_processing')->get($id);
        if ($row === null) {
            return null;
        }
        return $this->decodeRow($row->toArray(), self::PROCESSING_JSON_COLS);
    }

    /** @param array<string, mixed> $data */
    public function upsertProcessing(string $id, array $data): void
    {
        $payload = $this->encodeRow($data, self::PROCESSING_JSON_COLS);
        $payload['id'] = $id;
        $payload['updated_at'] = date('Y-m-d H:i:s');
        $existing = $this->db->table('gdpr_processing')->get($id);
        if ($existing !== null) {
            $existing->update($payload);
        } else {
            $this->db->table('gdpr_processing')->insert($payload);
        }
    }

    public function deleteProcessing(string $id): bool
    {
        return $this->db->table('gdpr_processing')->where('id', $id)->delete() > 0;
    }

    // ── DSAR log (Art. 12-22) ────────────────────────────────────────────

    /** @return list<array<string, mixed>> */
    public function listDsar(?string $status = null): array
    {
        $sel = $this->db->table('gdpr_dsar')->order('received_at DESC');
        if ($status !== null) {
            $sel->where('status', $status);
        }
        return array_map(
            fn(ActiveRow $r) => $this->decodeRow($r->toArray(), self::DSAR_JSON_COLS),
            iterator_to_array($sel)
        );
    }

    /** @param array<string, mixed> $data */
    public function recordDsar(array $data): int
    {
        $payload = $this->encodeRow($data, self::DSAR_JSON_COLS);
        $payload['updated_at'] = date('Y-m-d H:i:s');
        $row = $this->db->table('gdpr_dsar')->insert($payload);
        return (int) $row['id'];
    }

    // ── Breach register (Art. 33-34) ─────────────────────────────────────

    /** @return list<array<string, mixed>> */
    public function listBreaches(): array
    {
        return array_map(
            fn(ActiveRow $r) => $r->toArray(),
            iterator_to_array($this->db->table('gdpr_breaches')->order('detected_at DESC'))
        );
    }

    /** @param array<string, mixed> $data */
    public function recordBreach(array $data): int
    {
        $data['updated_at'] = date('Y-m-d H:i:s');
        $row = $this->db->table('gdpr_breaches')->insert($data);
        return (int) $row['id'];
    }

    // ── CSV export ────────────────────────────────────────────────────────

    /**
     * Stream the processing register as CSV (RFC 4180-ish). Caller is
     * responsible for setting Content-Type + Content-Disposition headers.
     */
    public function exportProcessingCsv(): string
    {
        $rows = $this->listProcessing();
        if ($rows === []) {
            return "id,name,purpose,legal_basis\n";
        }
        $headers = array_keys($rows[0]);
        $out = fopen('php://temp', 'w+');
        fputcsv($out, $headers);
        foreach ($rows as $row) {
            $line = [];
            foreach ($headers as $h) {
                $v = $row[$h] ?? '';
                if (is_array($v)) {
                    $v = implode('; ', $v);
                }
                $line[] = (string) $v;
            }
            fputcsv($out, $line);
        }
        rewind($out);
        $csv = stream_get_contents($out);
        fclose($out);
        return $csv === false ? '' : $csv;
    }

    // ── helpers ──────────────────────────────────────────────────────────

    /**
     * @param array<string, mixed> $row
     * @param list<string> $jsonCols
     * @return array<string, mixed>
     */
    private function decodeRow(array $row, array $jsonCols): array
    {
        foreach ($jsonCols as $col) {
            if (isset($row[$col]) && is_string($row[$col])) {
                $decoded = json_decode($row[$col], true);
                $row[$col] = is_array($decoded) ? $decoded : [];
            }
        }
        return $row;
    }

    /**
     * @param array<string, mixed> $row
     * @param list<string> $jsonCols
     * @return array<string, mixed>
     */
    private function encodeRow(array $row, array $jsonCols): array
    {
        foreach ($jsonCols as $col) {
            if (isset($row[$col]) && is_array($row[$col])) {
                $row[$col] = json_encode($row[$col], JSON_UNESCAPED_SLASHES);
            }
        }
        return $row;
    }
}
