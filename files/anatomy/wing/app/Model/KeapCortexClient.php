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
     * A taxonomy node with its children — the read `map` projects through.
     *
     * MEASURED 2026-08-10, and it corrects the record. The executor shipped with
     * five verbs late-bound because a probe found `/agent/v1/taxonomy` 401 and
     * concluded KEAP publishes nothing for them. The probe tested the paths the
     * DESIGN DOCUMENT named (docs/archive/nos-cortex-lang-wing-executor.md §3.4's table), not KEAP's actual surface: the route
     * is `/agent/v1/taxonomy/node/:id` and it answers 200 to the RO bearer,
     * carrying `children`, `ancestors`, `childCount`, `curated` and
     * `contentLink`. The bare `/agent/v1/taxonomy` 401 is the forward-auth
     * catch-all firing on a path with no agent route — which the handler's own
     * comment correctly identified as the MECHANISM while drawing the wrong
     * conclusion from it.
     *
     * @return array<string,mixed>|null
     */
    public function taxonomyNode(string $id): ?array
    {
        if ($id === '') {
            return null;
        }
        $res = $this->request('GET', '/agent/v1/taxonomy/node/' . rawurlencode($id));
        $node = $res['body']['data'] ?? null;
        return is_array($node) ? $node : null;
    }

    /**
     * Lexical taxonomy search. The read `classify` and `rank` stand on.
     *
     * @return list<array<string,mixed>>|null
     */
    public function taxonomySearch(string $query, int $limit = 20): ?array
    {
        if (trim($query) === '') {
            return null;
        }
        $res = $this->request('GET', '/agent/v1/taxonomy/search?q=' . rawurlencode($query)
            . '&limit=' . max(1, min($limit, 50)));
        $rows = $res['body']['data']['results'] ?? null;
        return is_array($rows) ? array_values($rows) : null;
    }

    /**
     * Hybrid (lexical + vector + graph) search, already ranked by KEAP.
     *
     * `legs` in the response says which of the three actually ran; a caller that
     * ignores it can read a purely lexical answer as a semantic one, so it is
     * returned alongside the rows rather than dropped.
     *
     * @return array{results:list<array<string,mixed>>,legs:array<string,mixed>}|null
     */
    public function semanticSearch(string $query, int $limit = 20): ?array
    {
        if (trim($query) === '') {
            return null;
        }
        $res = $this->request('GET', '/agent/v1/search/semantic?q=' . rawurlencode($query)
            . '&limit=' . max(1, min($limit, 50)));
        $data = $res['body']['data'] ?? null;
        if (!is_array($data) || !is_array($data['results'] ?? null)) {
            return null;
        }
        return [
            'results' => array_values($data['results']),
            'legs' => is_array($data['legs'] ?? null) ? $data['legs'] : [],
        ];
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
