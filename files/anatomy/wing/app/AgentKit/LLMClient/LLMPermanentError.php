<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * Permanent — runner should NOT retry (auth, deprecated model, bad request).
 * Triggers fallback URI if agent.yml has one, else terminates session.
 */
final class LLMPermanentError extends \RuntimeException
{
}
