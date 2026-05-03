<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Read-only HTTP client for Qdrant (Tier-2 vector DB at apps/qdrant.yml).
 *
 * Wing only QUERIES Qdrant (semantic search over agent_outputs /
 * system_metadata / cybersec_intel) — every write goes through Bone's
 * /api/v1/embeddings/upsert so the audit trail captures actor attribution.
 * Hence this client uses the READ-ONLY key (QDRANT_API_KEY_RO).
 *
 * Reads:
 *   QDRANT_URL          — e.g. http://127.0.0.1:6333  (empty = disabled)
 *   QDRANT_API_KEY_RO   — read-only api key
 *
 * On error or unconfigured state, returns ['error' => string, 'status' => int]
 * so presenters can proxy without try/catch noise (mirrors BoneClient pattern).
 */
class QdrantClient
{
	private string $baseUrl;
	private string $apiKey;
	private int $timeout;

	public function __construct(?string $baseUrl = null, ?string $apiKey = null, int $timeout = 10)
	{
		$this->baseUrl = rtrim($baseUrl ?? (string) (getenv('QDRANT_URL') ?: ''), '/');
		$this->apiKey  = $apiKey ?? (string) (getenv('QDRANT_API_KEY_RO') ?: '');
		$this->timeout = $timeout;
	}

	public function isConfigured(): bool
	{
		return $this->baseUrl !== '';
	}

	/** @return array{status:int,body:string} */
	private function request(string $method, string $path, ?array $body = null): array
	{
		if (!$this->isConfigured()) {
			return ['status' => 503, 'body' => '{"error":"QDRANT_URL is empty (install_qdrant=false)"}'];
		}

		$ch = curl_init($this->baseUrl . $path);
		$headers = ['Content-Type: application/json'];
		if ($this->apiKey !== '') {
			$headers[] = 'api-key: ' . $this->apiKey;
		}
		curl_setopt_array($ch, [
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_TIMEOUT        => $this->timeout,
			CURLOPT_CUSTOMREQUEST  => $method,
			CURLOPT_HTTPHEADER     => $headers,
			CURLOPT_POSTFIELDS     => $body !== null ? json_encode($body, JSON_UNESCAPED_SLASHES) : null,
		]);
		$out  = curl_exec($ch);
		$code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$err  = curl_error($ch);
		curl_close($ch);

		if ($out === false) {
			return ['status' => 0, 'body' => json_encode(['error' => $err ?: 'curl failed', 'status' => 0])];
		}
		return ['status' => $code, 'body' => (string) $out];
	}

	/** @return array<string, mixed> */
	private function json(string $method, string $path, ?array $body = null): array
	{
		$r = $this->request($method, $path, $body);
		$decoded = json_decode($r['body'], true);
		if (!is_array($decoded)) {
			return ['error' => 'non-json response', 'status' => $r['status'], 'raw' => $r['body']];
		}
		if ($r['status'] >= 400) {
			return ['error' => $decoded['status']['error'] ?? $decoded['error'] ?? 'http_error', 'status' => $r['status']];
		}
		return $decoded;
	}

	/** @return array<string, mixed> */
	public function health(): array
	{
		return $this->json('GET', '/healthz');
	}

	/** @return array<int, string> */
	public function listCollections(): array
	{
		$resp = $this->json('GET', '/collections');
		$collections = $resp['result']['collections'] ?? [];
		$names = [];
		foreach ($collections as $c) {
			if (isset($c['name'])) {
				$names[] = (string) $c['name'];
			}
		}
		return $names;
	}

	/** @return array<string, mixed> */
	public function collectionInfo(string $name): array
	{
		return $this->json('GET', '/collections/' . rawurlencode($name));
	}

	/**
	 * k-NN search.
	 *
	 * @param array<int, float> $vector
	 * @return array<int, array<string, mixed>>
	 */
	public function search(string $collection, array $vector, int $limit = 10, ?array $filter = null): array
	{
		$body = ['vector' => $vector, 'limit' => $limit, 'with_payload' => true];
		if ($filter !== null) {
			$body['filter'] = $filter;
		}
		$resp = $this->json('POST', '/collections/' . rawurlencode($collection) . '/points/search', $body);
		return is_array($resp['result'] ?? null) ? $resp['result'] : [];
	}
}
