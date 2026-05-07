<?php

declare(strict_types=1);

namespace App\AgentKit\Telemetry;

/**
 * One OpenTelemetry span. Closed via end(); converted to OTLP/JSON via
 * toOtlp(). Status codes follow the OTel spec: 0 = unset, 1 = ok, 2 = error.
 */
final class Span
{
	private int $endNanos = 0;
	/** @var array<string, scalar|null> */
	private array $attributes = [];
	private int $statusCode = 0; // 0=unset, 1=ok, 2=error
	private string $statusMessage = '';

	public function __construct(
		public readonly string $name,
		public readonly string $traceId,
		public readonly string $spanId,
		public readonly ?string $parentSpanId,
		public readonly int $startNanos,
		public readonly int $kind = 1, // 1=internal
	) {
	}

	public function setAttribute(string $key, mixed $value): self
	{
		if (is_scalar($value) || $value === null) {
			$this->attributes[$key] = $value;
		} elseif (is_array($value) || is_object($value)) {
			$this->attributes[$key] = json_encode($value) ?: '';
		}
		return $this;
	}

	/**
	 * @param array<string, scalar|null> $attrs
	 */
	public function setAttributes(array $attrs): self
	{
		foreach ($attrs as $k => $v) {
			$this->setAttribute($k, $v);
		}
		return $this;
	}

	public function end(?int $endNanos = null): self
	{
		$this->endNanos = $endNanos ?? (int) (microtime(true) * 1_000_000_000);
		if ($this->statusCode === 0) {
			$this->statusCode = 1;
		}
		return $this;
	}

	public function setOk(): self
	{
		$this->statusCode = 1;
		return $this;
	}

	public function setError(string $message): self
	{
		$this->statusCode = 2;
		$this->statusMessage = $message;
		$this->setAttribute('error', true);
		$this->setAttribute('error.message', $message);
		return $this;
	}

	/**
	 * @return array<string, mixed>
	 */
	public function toOtlp(): array
	{
		$attrs = [];
		foreach ($this->attributes as $k => $v) {
			$attrs[] = [
				'key' => $k,
				'value' => $this->valueForOtlp($v),
			];
		}
		$out = [
			'traceId' => $this->traceId,
			'spanId' => $this->spanId,
			'name' => $this->name,
			'kind' => $this->kind,
			'startTimeUnixNano' => (string) $this->startNanos,
			'endTimeUnixNano' => (string) ($this->endNanos ?: $this->startNanos),
			'attributes' => $attrs,
			'status' => [
				'code' => $this->statusCode,
				'message' => $this->statusMessage,
			],
		];
		if ($this->parentSpanId !== null && $this->parentSpanId !== '') {
			$out['parentSpanId'] = $this->parentSpanId;
		}
		return $out;
	}

	/**
	 * @return array<string, mixed>
	 */
	private function valueForOtlp(mixed $v): array
	{
		if (is_string($v)) {
			return ['stringValue' => $v];
		}
		if (is_int($v)) {
			return ['intValue' => (string) $v];
		}
		if (is_float($v)) {
			return ['doubleValue' => $v];
		}
		if (is_bool($v)) {
			return ['boolValue' => $v];
		}
		return ['stringValue' => (string) ($v ?? '')];
	}
}
