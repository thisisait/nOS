<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * The backend cannot honour the SHAPE of this request — a capability refusal,
 * as opposed to a backend that is broken, unauthenticated, or deprecated.
 *
 * WHY A DISTINCT CLASS, argued once and here. `Runner::callWithRetry` answers
 * every `LLMPermanentError` by re-sending the SAME request to the agent's
 * fallback backend. For a permanent error that is a fact about the BACKEND
 * (auth, retired model), that is the right move: the request was fine, the
 * backend was not, and another backend may serve it. For a permanent error
 * that is a fact about the REQUEST — "I cannot be handed a tool schema" — the
 * same move inverts the refusal's whole point: `ClaudeCliAdapter` refuses
 * tools precisely so they are never silently dropped, and the fallback resend
 * handed those exact schemas to a backend that treats tools as a passthrough
 * hint. The loud refusal became the silent drop, one hop later, on a 32B
 * local model wearing the ceremony's identity.
 *
 * So the taxonomy is: TRANSIENT (retry, then fallback), PERMANENT (fallback),
 * CAPABILITY (propagate — no fallback, ever). A capability refusal names a
 * mismatch between what the request asks and what the backend speaks; sending
 * the identical request elsewhere either hits the same mismatch or changes
 * the request's meaning without anyone deciding to. Both are worse than the
 * error.
 *
 * Extends LLMPermanentError so every existing `catch (LLMPermanentError)`
 * outside the Runner still catches it — the narrowing is only where the
 * fallback decision is made.
 */
final class LLMCapabilityError extends LLMPermanentError
{
}
