<?php

declare(strict_types=1);

namespace App\Model;

/**
 * Reads the Ansible-generated service-registry.json and exposes self-hosted
 * services as a list enriched with IP:port / HTTPS links. Also performs
 * lightweight health probes (cached in-memory for the request lifetime).
 *
 * Registry file lives at ~/projects/default/service-registry.json. Path is
 * injected via DI parameter `services.registry.path`.
 */
final class ServiceRegistry
{
	/** @var list<array<string,mixed>>|null */
	private ?array $cachedServices = null;

	/** @var array<string,array{status:string,http_code:int,ms:int}> */
	private array $healthCache = [];

	public function __construct(
		private string $registryPath,
	) {
	}


	/**
	 * Returns the parsed registry including meta (generated_at, hostname, domain)
	 * + enriched services with IP:port links.
	 *
	 * @return array{generated_at:?string,hostname:?string,domain:?string,services:list<array<string,mixed>>}
	 */
	public function read(): array
	{
		$raw = $this->readRaw();
		$services = [];
		foreach (($raw['services'] ?? []) as $svc) {
			$services[] = $this->enrich($svc);
		}
		$this->cachedServices = $services;
		return [
			'generated_at' => $raw['generated_at'] ?? null,
			'hostname' => $raw['hostname'] ?? null,
			'domain' => $raw['domain'] ?? null,
			'services' => $services,
		];
	}


	/**
	 * Returns services grouped by category (observability, iiab, b2b, ...).
	 *
	 * @return array<string,list<array<string,mixed>>>
	 */
	public function grouped(): array
	{
		$data = $this->read();
		$groups = [];
		foreach ($data['services'] as $svc) {
			$key = $svc['category'] ?? 'other';
			$groups[$key][] = $svc;
		}
		ksort($groups);
		return $groups;
	}


	/**
	 * Probe a single service URL via cURL HEAD. Cache is per-request only.
	 * Returns {status: up|down|skipped, http_code, ms}.
	 *
	 * @return array{status:string,http_code:int,ms:int}
	 */
	public function probe(string $url, float $timeoutSeconds = 2.0): array
	{
		if (isset($this->healthCache[$url])) {
			return $this->healthCache[$url];
		}

		$start = microtime(true);
		$handle = curl_init($url);
		if ($handle === false) {
			return $this->healthCache[$url] = ['status' => 'skipped', 'http_code' => 0, 'ms' => 0];
		}
		curl_setopt_array($handle, [
			CURLOPT_NOBODY => true,
			CURLOPT_FOLLOWLOCATION => false,
			CURLOPT_SSL_VERIFYPEER => false,
			CURLOPT_SSL_VERIFYHOST => 0,
			CURLOPT_TIMEOUT => (int) ceil($timeoutSeconds),
			CURLOPT_CONNECTTIMEOUT_MS => (int) ($timeoutSeconds * 1000),
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_USERAGENT => 'Glasswing-Hub/1.0',
		]);
		curl_exec($handle);
		$code = (int) curl_getinfo($handle, CURLINFO_HTTP_CODE);
		$errno = curl_errno($handle);
		curl_close($handle);
		$ms = (int) round((microtime(true) - $start) * 1000);

		// 2xx/3xx/401/403 (auth gate) = up — the service is answering
		$status = ($code >= 200 && $code < 500 && $errno === 0) ? 'up' : 'down';

		return $this->healthCache[$url] = [
			'status' => $status,
			'http_code' => $code,
			'ms' => $ms,
		];
	}


	/**
	 * Probe every service in registry and return [url => result].
	 *
	 * @return array<string,array{status:string,http_code:int,ms:int}>
	 */
	public function probeAll(float $timeoutSeconds = 2.0): array
	{
		$out = [];
		foreach ($this->read()['services'] as $svc) {
			$url = $svc['url'] ?? null;
			if (!$url || !is_string($url)) {
				continue;
			}
			$out[$url] = $this->probe($url, $timeoutSeconds);
		}
		return $out;
	}


	/**
	 * @return array<string,mixed>
	 */
	private function readRaw(): array
	{
		if (!is_file($this->registryPath) || !is_readable($this->registryPath)) {
			return ['services' => []];
		}
		$json = @file_get_contents($this->registryPath);
		if ($json === false || $json === '') {
			return ['services' => []];
		}
		$data = json_decode($json, true);
		return is_array($data) ? $data : ['services' => []];
	}


	/**
	 * @param array<string,mixed> $svc
	 * @return array<string,mixed>
	 */
	private function enrich(array $svc): array
	{
		$port = isset($svc['port']) && is_int($svc['port']) ? $svc['port'] : 0;
		$domain = isset($svc['domain']) && is_string($svc['domain']) ? $svc['domain'] : null;
		$svc['ip_url'] = $port > 0 ? 'http://127.0.0.1:' . $port : null;
		$svc['domain_url'] = $domain ? 'https://' . $domain : null;
		$svc['primary_url'] = $svc['url'] ?? $svc['domain_url'] ?? $svc['ip_url'];
		return $svc;
	}
}
