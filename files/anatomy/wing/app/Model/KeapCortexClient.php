<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Wing -> KEAP, over loopback, with the RO agent bearer.
 *
 * THE DESIGN CALLED THIS "the one genuine integration risk" — Wing is a host
 * launchd process, KEAP a container on `gated_net` only, and host-to-container
 * is not automatic. Measured 2026-08-08 and it is already solved:
 *
 *     docker port iiab-keap-1        8080/tcp -> 127.0.0.1:8091
 *     host -> /agent/v1/health       200 in 0.09s
 *     wing daemon env                KEAP_API_URL, KEAP_AGENT_TOKEN_RO, _RW
 *
 * The daemon already carries the URL and both tokens, declared in its plist —
 * which also answers docs/archive/nos-cortex-lang-wing-executor.md §8.5 ("confirm which role owns the mint": `pazny.wing`
 * renders them). So the executor is a Wing-only build with no network work.
 *
 * The RO token is used deliberately even though the RW one is present: nothing
 * this client does may write, and reaching for the weaker credential is how
 * that stays true when someone later adds a method here in a hurry.
 */
final class KeapCortexClient
{
    private const TIMEOUT = 20;

    public function __construct(
        private readonly ?string $baseUrl = null,
        private readonly ?string $token = null,
    ) {
    }

    private function url(): string
    {
        $u = $this->baseUrl ?: (getenv('KEAP_API_URL') ?: 'http://127.0.0.1:8091');
        return rtrim($u, '/');
    }

    private function bearer(): string
    {
        return $this->token ?: (string) (getenv('KEAP_AGENT_TOKEN_RO') ?: '');
    }

    public function configured(): bool
    {
        return $this->bearer() !== '';
    }

    /**
     * Phase-1 authority. Returns the decoded `data` envelope, or null when KEAP
     * could not be reached or answered a shape we do not recognise.
     *
     * NULL AND `valid:false` ARE DIFFERENT ANSWERS and the caller must keep them
     * apart: `valid:false` is KEAP saying the program is wrong (a 200 to the
     * caller, with the errors passed through so a repair loop can act); null is
     * KEAP saying nothing at all (a 502). Collapsing them would report an
     * unreachable validator as a bad program.
     *
     * @return array<string,mixed>|null
     */
    public function validate(string $source, ?int $ttlSeconds = null): ?array
    {
        $body = ['source' => $source];
        if ($ttlSeconds !== null) {
            $body['ttlSeconds'] = $ttlSeconds;
        }
        $res = $this->request('POST', '/agent/v1/validate', $body);
        if ($res === null || !is_array($res['body'] ?? null)) {
            return null;
        }
        $env = $res['body'];
        if (($env['success'] ?? false) !== true || !is_array($env['data'] ?? null)) {
            return null;
        }
        return $env['data'];
    }

    /**
     * The published opcode registry, for the boot coverage gate.
     *
     * @return array{opcodes:list<array<string,mixed>>,registryHash:string}|null
     */
    public function publishedOpcodes(): ?array
    {
        $res = $this->request('GET', '/agent/v1/validate/opcodes');
        $data = $res['body']['data'] ?? null;
        if (!is_array($data) || !is_array($data['opcodes'] ?? null)) {
            return null;
        }
        return [
            'opcodes' => array_values($data['opcodes']),
            'registryHash' => (string) ($data['registryHash'] ?? ''),
        ];
    }

    /**
     * Relations touching a ref. KEAP has no per-ref filter on this route, so the
     * narrowing happens here — and `limit` is applied AFTER it, or a caller
     * asking for 5 would get the first 5 of everything instead of 5 of theirs.
     *
     * @return list<array<string,mixed>>|null
     */
    public function relations(string $ref, int $limit = 20): ?array
    {
        $res = $this->request('GET', '/agent/v1/relations?limit=500');
        $rows = $res['body']['data']['relations'] ?? null;
        if (!is_array($rows)) {
            return null;
        }
        if ($ref === '') {
            return array_slice(array_values($rows), 0, $limit);
        }
        $hit = [];
        foreach ($rows as $r) {
            if (($r['fromRef'] ?? null) === $ref || ($r['toRef'] ?? null) === $ref) {
                $hit[] = $r;
            }
        }
        return array_slice($hit, 0, $limit);
    }

    /**
     * @param array<string,mixed>|null $json
     * @return array{status:int,body:mixed}|null
     */
    private function request(string $method, string $path, ?array $json = null): ?array
    {
        $bearer = $this->bearer();
        if ($bearer === '') {
            return null;
        }
        $headers = ['Authorization: Bearer ' . $bearer, 'Accept: application/json'];
        $opts = ['http' => [
            'method' => $method,
            'timeout' => self::TIMEOUT,
            // Without this a 4xx/5xx makes file_get_contents return false and
            // emit a warning, and the status — the thing that distinguishes a
            // refusal from an outage — is lost.
            'ignore_errors' => true,
        ]];
        if ($json !== null) {
            $headers[] = 'Content-Type: application/json';
            $opts['http']['content'] = json_encode($json, JSON_UNESCAPED_UNICODE);
        }
        $opts['http']['header'] = implode("\r\n", $headers);

        $raw = @file_get_contents($this->url() . $path, false, stream_context_create($opts));
        if ($raw === false) {
            return null;
        }
        $status = 0;
        foreach ($http_response_header ?? [] as $h) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $h, $m)) {
                $status = (int) $m[1];
            }
        }
        return ['status' => $status, 'body' => json_decode($raw, true)];
    }
}
