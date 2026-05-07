<?php

declare(strict_types=1);

namespace App\AgentKit\Telemetry;

/**
 * OTLP/HTTP span exporter. Posts batches of OpenTelemetry spans to Alloy on
 * 127.0.0.1:4318 (the existing Alloy host config opens both 4317 gRPC and
 * 4318 HTTP). Alloy forwards traces to Tempo where /agents UI links them.
 *
 * We hand-write the OTLP/HTTP JSON shape rather than depending on the full
 * open-telemetry/sdk because:
 *  - PHP SDK requires a long-running provider/processor with backpressure
 *    handling that doesn't fit a request-scoped Wing process
 *  - The OTLP-JSON shape is small and stable (proto3 -> JSON mapping)
 *  - We can fail-soft: an OTel hiccup must NEVER crash an agent run
 *
 * Failures are best-effort: caught + logged, never raised. Audit
 * (AuditEmitter, separate path) is the source of truth; OTel is the
 * cross-tool view in Tempo.
 */
final class OtelExporter
{
    private string $endpoint;
    private float $timeoutSeconds;
    private string $serviceName;

    public function __construct(
        ?string $endpoint = null,
        float $timeoutSeconds = 2.0,
        string $serviceName = 'nos.agentkit',
    ) {
        $this->endpoint = rtrim(
            $endpoint ?? (getenv('OTEL_EXPORTER_OTLP_ENDPOINT') ?: 'http://127.0.0.1:4318'),
            '/'
        );
        $this->timeoutSeconds = $timeoutSeconds;
        $this->serviceName = $serviceName;
    }

    /**
     * @param array<int, Span> $spans
     */
    public function export(array $spans): bool
    {
        if ($spans === []) {
            return true;
        }

        $payload = [
            'resourceSpans' => [[
                'resource' => [
                    'attributes' => [
                        $this->kv('service.name', $this->serviceName),
                        $this->kv('service.namespace', 'nos'),
                    ],
                ],
                'scopeSpans' => [[
                    'scope' => ['name' => 'app.agentkit'],
                    'spans' => array_map(fn (Span $s) => $s->toOtlp(), $spans),
                ]],
            ]],
        ];

        $ch = curl_init($this->endpoint . '/v1/traces');
        if ($ch === false) {
            return false;
        }
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_SLASHES),
            CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
            CURLOPT_TIMEOUT_MS => (int) ($this->timeoutSeconds * 1000),
        ]);
        curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        // curl_close removed - no-op since PHP 8.0, deprecation in 8.5

        return $status >= 200 && $status < 300;
    }

    /**
     * @return array{key: string, value: array<string, string>}
     */
    private function kv(string $key, string $value): array
    {
        return [
            'key' => $key,
            'value' => ['stringValue' => $value],
        ];
    }
}
