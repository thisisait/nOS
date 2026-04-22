<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Thin HTTP client for BoxAPI (files/boxapi/main.py).
 *
 * Reads BOXAPI_URL (default http://127.0.0.1:8069) and BOXAPI_SECRET from
 * environment — both populated by the boxapi Ansible role and surfaced to
 * PHP via the nginx fastcgi_param block.
 *
 * All methods return decoded JSON. On non-2xx or network errors, returns
 * ['error' => string, 'status' => int] so presenters can proxy verbatim.
 */
class BoxApiClient
{
	private string $baseUrl;
	private string $secret;
	private int $timeout;

	public function __construct(?string $baseUrl = null, ?string $secret = null, int $timeout = 30)
	{
		$this->baseUrl = rtrim($baseUrl ?? getenv('BOXAPI_URL') ?: 'http://127.0.0.1:8069', '/');
		$this->secret  = $secret ?? (string) (getenv('BOXAPI_SECRET') ?: '');
		$this->timeout = $timeout;
	}

	/** @return array{status:int,body:mixed} */
	public function get(string $path, array $query = []): array
	{
		$url = $this->baseUrl . $path;
		if ($query) {
			$url .= '?' . http_build_query($query);
		}
		return $this->send('GET', $url, null);
	}

	/** @return array{status:int,body:mixed} */
	public function post(string $path, ?array $body = null): array
	{
		return $this->send('POST', $this->baseUrl . $path, $body);
	}

	/**
	 * @return array{status:int,body:mixed}
	 */
	private function send(string $method, string $url, ?array $body): array
	{
		$ch = curl_init();
		curl_setopt_array($ch, [
			CURLOPT_URL            => $url,
			CURLOPT_CUSTOMREQUEST  => $method,
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_TIMEOUT        => $this->timeout,
			CURLOPT_CONNECTTIMEOUT => 5,
			CURLOPT_HTTPHEADER     => [
				'Content-Type: application/json',
				'Accept: application/json',
				'X-API-Key: ' . $this->secret,
			],
		]);
		if ($body !== null) {
			curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body));
		}

		$raw = curl_exec($ch);
		$status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
		$err = curl_error($ch);
		curl_close($ch);

		if ($raw === false || $status === 0) {
			return [
				'status' => 502,
				'body'   => ['error' => 'BoxAPI unreachable', 'detail' => $err],
			];
		}

		$decoded = json_decode((string) $raw, true);
		return [
			'status' => $status,
			'body'   => $decoded ?? ['raw' => $raw],
		];
	}
}
