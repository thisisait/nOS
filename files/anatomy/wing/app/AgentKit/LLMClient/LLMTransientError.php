<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * Transient — runner should retry with backoff (rate limit, 5xx, network).
 */
final class LLMTransientError extends \RuntimeException
{
}
