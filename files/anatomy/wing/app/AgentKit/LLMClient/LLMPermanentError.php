<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * Permanent — runner should NOT retry (auth, deprecated model, bad request).
 * Triggers fallback URI if agent.yml has one, else terminates session.
 *
 * Un-finaled 2026-08-12 for exactly one subclass: `LLMCapabilityError`, the
 * refusal that must NOT trigger the fallback (see its docblock). The subclass
 * relationship is load-bearing — every `catch (LLMPermanentError)` outside the
 * Runner's fallback gate keeps catching capability refusals.
 */
class LLMPermanentError extends \RuntimeException
{
}
