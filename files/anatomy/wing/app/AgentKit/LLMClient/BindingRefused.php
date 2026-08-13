<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * A binding that must not be honoured — and must not be degraded around.
 *
 * Distinct from "declared but disarmed" (which the resolver answers with the
 * DEFAULT backend plus an audit event, mirroring prepared-not-armed): a
 * refusal means the declaration itself is wrong — an unknown backend, a
 * deferred agent being armed, an opus-pinned ceremony routed foreign, a
 * routing the agent's own Article-30 record does not declare, or an armed
 * backend with no model id. Serving such a run on ANY backend would execute
 * a ceremony whose declared compliance state is false, so the session must
 * refuse to open. Runner's generic Throwable handler turns this into a
 * terminated session with the message in error_json, which is exactly the
 * visibility a wrong declaration deserves.
 */
final class BindingRefused extends \RuntimeException
{
}
