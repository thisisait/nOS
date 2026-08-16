<?php

declare(strict_types=1);

namespace App\AgentKit;

/**
 * A session hit its wall-clock or token ceiling and was stopped.
 *
 * DELIBERATELY NOT an LLM error. `LLMTransientError` would be retried and
 * `LLMPermanentError` would fall back to the secondary model — both of which
 * spend more, which is the one thing a ceiling exists to prevent. This is a
 * Runner-level refusal: the run ends, the reason is recorded, and nothing
 * downstream treats it as something to work around.
 *
 * Introduced 2026-08-16 with the ceilings themselves. Before them the caps
 * were per-iteration and multiplied — roughly fifteen hours for one stuck
 * agent, with no token bound at all.
 */
final class SessionCeilingReached extends \RuntimeException
{
}
