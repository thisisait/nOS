<?php

declare(strict_types=1);

namespace App\Presenters\Api;

use App\Cortex\CortexBindingGate;
use App\Cortex\CortexCapability;
use App\Cortex\CortexContext;
use App\Cortex\CortexOpcodeRegistry;
use App\Cortex\ResolvedStage;
use App\Model\EventRepository;
use App\Model\KeapCortexClient;

/**
 * The cortex-lang executor — P1, read verbs, synchronous.
 *
 * AUTHORITY SEPARATION, which is the whole design in one line: KEAP owns
 * MEANING and Wing owns PERMISSION. KEAP's own contract says so — its validate
 * response carries `scope.authorizes: false` as a literal. So `valid: true` is
 * never treated here as "may run"; it is treated as "is a program".
 *
 * SYNCHRONOUS ON PURPOSE. Every P1 verb is a loopback read that returns in
 * milliseconds. A detached spawn with a status endpoint and a session row would
 * be machinery for a wait that does not happen. That surface belongs to write
 * verbs, and write verbs are refused here
 * (docs/archive/nos-cortex-lang-wing-executor.md §6).
 *
 * THE CALLER SENDS SOURCE, NEVER AN AST. Wing re-POSTs to KEAP on every dispatch
 * and executes the AST that comes back. A caller may send its cached `binding`
 * to prove it is looking at the same world — proving freshness and supplying the
 * program are different powers, and only the first is delegated.
 */
final class CortexExecutorPresenter extends BaseApiPresenter
{
    /** @inject */
    public KeapCortexClient $keap;

    /** @inject */
    public CortexOpcodeRegistry $opcodes;

    /** @inject */
    public CortexBindingGate $binding;

    /** @inject */
    public EventRepository $events;

    private ?CortexCapability $capability = null;

    public function startup(): void
    {
        parent::startup();

        // The brain token is refused at the door. It authenticates every other
        // Wing route, and if it opened this one the capability axes below would
        // be decoration — anyone holding it could run any verb anywhere.
        $this->capability = CortexCapability::fromToken($this->validatedToken);
        if ($this->capability === null) {
            $this->sendError(
                'this token carries no cortex capability. The executor is reachable '
                . 'only by a token scoped on all three axes (verbs, namespaces, '
                . 'tenants); a token that is powerful elsewhere is not a way in.',
                403
            );
        }
    }

    /**
     * GET /api/v1/cortex/opcodes — what this deployment can actually dispatch.
     *
     * Reports coverage against KEAP's published registry rather than asserting
     * it, so an operator can see the gap instead of trusting a boolean someone
     * wrote once.
     */
    public function actionOpcodes(): void
    {
        $this->requireMethod('GET');
        $published = $this->keap->publishedOpcodes();
        $mine = $this->opcodes->opcodes();

        $uncovered = [];
        if ($published !== null) {
            foreach ($published['opcodes'] as $op) {
                if (!($op['mutating'] ?? false) && !$this->opcodes->has((string) ($op['name'] ?? ''))) {
                    $uncovered[] = (string) $op['name'];
                }
            }
        }
        $this->sendSuccess([
            'handlers' => $mine,
            'registry_hash' => $published['registryHash'] ?? null,
            // Null, not true, when KEAP could not be asked. "We could not check"
            // and "we checked and it is fine" are different answers.
            'covers_keap' => $published === null ? null : $uncovered === [],
            'uncovered' => $uncovered,
        ]);
    }

    /** POST /api/v1/cortex/execute */
    public function actionExecute(): void
    {
        $this->requireMethod('POST');
        $body = $this->getJsonBody();

        $source = $body['source'] ?? null;
        if (!is_string($source) || trim($source) === '') {
            $this->sendError('`source` is required and must be a cortex-lang program', 422);
        }

        // docs/archive/nos-cortex-lang-wing-executor.md §6 write-future gate. Refused in P1 rather than ignored: a caller that
        // asked to commit and got a read must not read the 200 as "committed".
        if (!empty($body['commit'])) {
            $this->sendError('mutating execution is not available in P1; `commit` must be false', 403);
        }

        $actor = $this->getActorId();
        // The body may NARROW the tenant, never widen it. Taking the tenant from
        // the body alone would let a caller name someone else's.
        $tenant = is_string($body['tenant'] ?? null) && $body['tenant'] !== ''
            ? (string) $body['tenant'] : 'default';
        if (!$this->capability->allowsTenant($tenant)) {
            $this->reject('tenant', $tenant, $actor);
            $this->sendError("this token may not execute in tenant '{$tenant}'", 403);
        }

        if (!$this->keap->configured()) {
            $this->sendError('KEAP_AGENT_TOKEN_RO is not configured; nothing can be validated', 502);
        }

        // 1 — phase-1 authority, on every dispatch.
        $ttl = isset($body['ttlSeconds']) && is_int($body['ttlSeconds']) ? $body['ttlSeconds'] : null;
        $report = $this->keap->validate($source, $ttl);
        if ($report === null) {
            // Distinct from valid:false on purpose. An unreachable validator is
            // not a bad program, and reporting it as one would send a caller to
            // debug their source while KEAP is down.
            $this->sendError('KEAP validate is unreachable or answered an unrecognised envelope', 502);
        }

        // 2 — not valid is a 200 with the errors passed through verbatim, so a
        // repair loop can act on codes and spans without parsing prose.
        if (($report['valid'] ?? false) !== true) {
            $this->sendSuccess([
                'valid' => false, 'ast' => null, 'dispatched' => false,
                'errors' => $report['errors'] ?? [], 'warnings' => $report['warnings'] ?? [],
            ]);
        }

        $ast = (array) ($report['ast'] ?? []);
        $bind = (array) ($ast['binding'] ?? []);

        // 3 — identity and freshness.
        $drift = $this->binding->check($bind, is_array($body['ast_binding'] ?? null) ? $body['ast_binding'] : null);
        if ($drift !== null) {
            $this->reject('binding', $drift['code'], $actor);
            $this->getHttpResponse()->setCode(409);
            $this->sendJson(['error' => $drift['detail'], 'code' => $drift['code']]);
        }

        $stages = array_values((array) ($ast['pipeline']['stages'] ?? []));

        // 5 — every stage is gated BEFORE any stage runs. Interleaving would let
        // stage 0 execute and stage 1 be refused, which is a partial effect
        // nobody asked for, and on a read surface still a disclosure.
        foreach ($stages as $raw) {
            $stage = ResolvedStage::fromAst((array) $raw);

            if ($stage->mutating) {
                $this->reject('mutating', $stage->opcode, $actor);
                $this->sendError("mutating verb '{$stage->opcode}' is not dispatchable in P1", 501);
            }
            if (!$this->opcodes->has($stage->opcode)) {
                $this->reject('no_handler', $stage->opcode, $actor);
                $this->sendError("no handler for opcode '{$stage->opcode}'", 501);
            }
            if (!$this->capability->allowsVerb($stage->opcode)) {
                $this->reject('verb', $stage->opcode, $actor);
                $this->sendError("this token may not execute '{$stage->opcode}'", 403);
            }
            foreach ($stage->namespaces() as $ns) {
                // kg/ent can never appear in a valid AST — KEAP constant-rejects
                // them. One reaching here is a breach of KEAP's contract, not a
                // caller's mistake, so it is a 500 and it is audited.
                if ($ns === 'kg' || $ns === 'ent') {
                    $this->reject('invariant', $ns, $actor);
                    $this->sendError(
                        "namespace '{$ns}' reached a handler inside a valid AST — "
                        . 'KEAP contract violation, nothing was dispatched',
                        500
                    );
                }
                if (!$this->capability->allowsNamespace($ns)) {
                    $this->reject('namespace', $ns, $actor);
                    $this->sendError("this token may not reach namespace '{$ns}'", 403);
                }
                $accepted = $this->opcodes->handler($stage->opcode)->acceptedNamespaces();
                if (!in_array($ns, $accepted, true)) {
                    $this->reject('handler_namespace', "{$stage->opcode}/{$ns}", $actor);
                    $this->sendError(
                        "handler '{$stage->opcode}' does not accept namespace '{$ns}'", 422
                    );
                }
            }
        }

        // 6 — dispatch, one audited action per stage.
        $out = [];
        foreach ($stages as $raw) {
            $stage = ResolvedStage::fromAst((array) $raw);
            $actionId = 'cx-' . bin2hex(random_bytes(10));
            $ctx = new CortexContext($actor, $tenant, $actionId);

            $this->audit('cortex_stage_begin', $stage->opcode, $actor, $actionId, [
                'index' => $stage->index, 'ns' => $stage->namespaces(), 'tenant' => $tenant,
            ]);
            $result = $this->opcodes->handler($stage->opcode)->execute($stage, $ctx);
            $this->audit('cortex_stage_finish', $stage->opcode, $actor, $actionId, [
                'index' => $stage->index, 'effect' => $result->effect,
                'rows' => count($result->rows), 'code' => $result->code,
            ]);

            $out[] = [
                'index' => $stage->index,
                'opcode' => $stage->opcode,
                'ns' => $stage->namespaces(),
                'result' => $result->toArray(),
                'audited_action_id' => $actionId,
            ];
        }

        $this->sendSuccess([
            'valid' => true,
            'complete' => (bool) ($report['complete'] ?? false),
            'dispatched' => true,
            'stages' => $out,
            'binding' => $bind,
        ]);
    }

    /**
     * A refusal is a first-class audit row, not a log line.
     *
     * Without this, the only trace of "someone tried to reach the GDPR store
     * with a token that may not" is an HTTP status in a proxy log nobody
     * queries. A refused attempt is the most interesting thing this endpoint
     * ever records.
     */
    private function reject(string $gate, string $detail, ?string $actor): void
    {
        $this->audit('cortex_dispatch_reject', $detail, $actor, 'cx-' . bin2hex(random_bytes(10)), [
            'gate' => $gate,
        ]);
    }

    /** @param array<string,mixed> $payload */
    private function audit(string $type, string $task, ?string $actor, string $actionId, array $payload): void
    {
        try {
            // insert(), and `result` (an array it encodes) rather than
            // `result_json`. The first draft called record() with result_json —
            // neither exists, and `php -l` was happy with both, which is the
            // whole reason a lint is not a load.
            $this->events->insert([
                'ts' => (new \DateTimeImmutable())->format('Y-m-d\TH:i:s.v\Z'),
                'run_id' => $actionId,
                'type' => $type,
                'task' => $task,
                'source' => 'cortex-executor',
                'actor_id' => $actor,
                'actor_action_id' => $actionId,
                'acted_at' => (new \DateTimeImmutable())->format('c'),
                'result' => $payload,
            ]);
        } catch (\Throwable $e) {
            // An audit failure must not swallow the caller's answer, and it must
            // not pass silently either — the response still carries the action
            // id, so a missing row is findable rather than invisible.
            error_log('cortex audit write failed: ' . $e->getMessage());
        }
    }
}
