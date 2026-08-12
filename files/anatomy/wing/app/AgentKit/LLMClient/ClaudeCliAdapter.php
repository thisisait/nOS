<?php

declare(strict_types=1);

namespace App\AgentKit\LLMClient;

/**
 * The local `claude` CLI, as an AgentKit client.
 *
 * WHY THIS IS THE FIRST PIECE OF `w-agentkit-spine`. The estate runs two agent
 * runtimes: `pulse-run-agent.sh` → `claude` (the one that executes the eight
 * nightly ceremonies) and AgentKit PHP (the one that records sessions,
 * iterations, grader decisions, vault indirection and `actor_action_id`
 * lineage). Everything the operator asked of AgentKit is a property of the
 * runtime that is NOT running the agents, and the reason is narrower than "two
 * runtimes": AgentKit had no client for the only backend this machine can
 * actually drive. `Factory` knew `anthropic-*` (needs ANTHROPIC_API_KEY, which
 * this estate does not use) and `openclaw-*` (a local gateway that was dead for
 * weeks). Measured 2026-08-11: `agent_sessions` holds 3 rows for all time,
 * every one written by the shell bridge; `agent_iterations` holds 0.
 *
 * WHAT THIS ADAPTER CANNOT DO, stated rather than papered over.
 * `LLMClientInterface::send()` takes `$tools` and callers read `tool_use` blocks
 * off the response to drive AgentKit's own loop. The CLI does not expose that
 * protocol: invoked as `--print --output-format json`, it runs its OWN tool loop
 * internally (that is what `--permission-mode bypassPermissions` is for) and
 * returns one final assistant message. So a tool schema handed to this adapter
 * could not be honoured, and honouring nothing quietly is precisely the defect
 * `MapHandler` shipped and had to be corrected for the same day — an argument
 * visible in the source and absent from the behaviour. It REFUSES instead.
 *
 * The consequence is a real boundary, not a temporary one: agents whose ceremony
 * is self-contained (the CLI calls Wing and KEAP itself, which is how all eight
 * nightly jobs are written) run here; agents that need AgentKit to mediate each
 * tool call need a backend that speaks the tool protocol. Naming that boundary
 * is what lets the cutover be planned instead of discovered.
 *
 * `--print --output-format json` yields `.result` (final text), `.usage` (token
 * tally) and `.total_cost_usd`, which is what makes a real `LLMResponse`
 * possible — `pulse-run-agent.sh:266-270` records the same discovery, and the
 * two call sites must stay in step until one of them is retired.
 */
final class ClaudeCliAdapter implements LLMClientInterface
{
    /**
     * @param string $modelUri  full URI, e.g. `claude-sonnet`
     * @param string $model     what `--model` receives, e.g. `sonnet`
     * @param string $binary    resolved `claude` path
     * @param int    $timeoutS  wall clock for one call
     */
    public function __construct(
        private readonly string $modelUri,
        private readonly string $model,
        private readonly string $binary = 'claude',
        private readonly int $timeoutS = 900,
    ) {
    }

    public function identifier(): string
    {
        return $this->modelUri;
    }

    public function send(
        string $systemPrompt,
        array $messages,
        array $tools = [],
        int $maxTokens = 4096,
    ): LLMResponse {
        if ($tools !== []) {
            // LLMCapabilityError, not the plain permanent class: the Runner
            // answers a permanent error by re-sending the SAME request to the
            // fallback backend, and for THIS refusal that resend would hand the
            // tool schemas to a backend that treats them as a hint — the exact
            // silent drop this throw exists to prevent, one hop later. A
            // capability refusal is about the request's shape and must
            // propagate; see LLMCapabilityError's docblock for the argument.
            throw new LLMCapabilityError(sprintf(
                "the claude CLI backend cannot be handed a tool schema: invoked as "
                . '`--print`, it runs its own tool loop and returns a final message, '
                . 'so the %d tool(s) offered here would be silently dropped. Give '
                . 'this agent a backend that speaks the tool protocol, or write its '
                . 'ceremony so the CLI calls the surfaces itself.',
                count($tools)
            ));
        }

        // The CLI takes ONE prompt. Messages are folded in role order rather
        // than only the last one being sent: a caller that built a thread and
        // got a reply to its final line would look like it had context it did
        // not have.
        $prompt = $this->fold($messages);
        if (trim($prompt) === '') {
            throw new LLMPermanentError('no message content to send');
        }

        $argv = [$this->binary, '--print', '--output-format', 'json',
                 '--permission-mode', 'bypassPermissions'];
        if (trim($systemPrompt) !== '') {
            $argv[] = '--system-prompt';
            $argv[] = $systemPrompt;
        }
        if ($this->model !== '') {
            // Without an explicit model the CLI falls back to the operator's
            // default — the most expensive tier — which bulk ceremonies must
            // never inherit. Same reason pulse-run-agent.sh pins NOS_AGENT_MODEL.
            $argv[] = '--model';
            $argv[] = $this->model;
        }
        // `--` ends option parsing. Without it, a folded prompt that happens to
        // open with `-` is read as a flag — measured 2026-08-12 on claude 2.1.220:
        // `claude --print "-say OK"` dies with `error: unknown option '-say OK'`,
        // and a [USER] fold beginning with a dash is not exotic (a diff, a YAML
        // list, a CLI transcript). With `--` the same prompt is answered.
        $argv[] = '--';
        $argv[] = $prompt;

        // `$maxTokens` is HONOURED, via the one control the CLI exposes:
        // CLAUDE_CODE_MAX_OUTPUT_TOKENS caps every model call the CLI makes.
        // This adapter used to accept the parameter and read it never — the
        // exact shape its own tools refusal condemns ("an argument visible in
        // the source and absent from the behaviour"). Semantics differ from the
        // API's max_tokens, and the difference is handled below: the API
        // truncates and reports stop_reason=max_tokens; the CLI DISCARDS the
        // over-cap response and reports is_error (measured 2026-08-12: cap=100,
        // "count to 300" -> is_error:true, "response exceeded the 100 output
        // token maximum", usage still billed).
        [$exit, $stdout, $stderr] = $this->run($argv, [
            'CLAUDE_CODE_MAX_OUTPUT_TOKENS' => (string) max(1, $maxTokens),
        ]);

        $decoded = json_decode($stdout, true);
        if (!is_array($decoded)) {
            // A non-JSON answer is not a model refusal — it is the CLI dying
            // before it could speak, and treating it as content would put a
            // stack trace into an agent transcript as though it were reasoning.
            throw new LLMTransientError(sprintf(
                'claude CLI produced no JSON (exit %d). stderr: %s',
                $exit,
                mb_substr(trim($stderr), 0, 300) ?: '(empty)'
            ));
        }

        $usage = (array) ($decoded['usage'] ?? []);

        if (($decoded['is_error'] ?? false) || $exit !== 0) {
            $message = (string) ($decoded['result'] ?? $decoded['error'] ?? 'unknown error');

            // The cap was hit. The CLI discards the over-cap text instead of
            // truncating it, so this is rendered as what it is in the
            // vendor-neutral contract — stop_reason=max_tokens with no content —
            // rather than as a backend failure. A string match, because the CLI
            // gives the condition no structured code (`subtype` stays "success");
            // the phrase is pinned by the 2026-08-12 probe in send()'s comment.
            if (stripos($message, 'output token maximum') !== false) {
                return new LLMResponse(
                    stopReason: 'max_tokens',
                    contentBlocks: [],
                    tokensInput: (int) ($usage['input_tokens'] ?? 0),
                    tokensOutput: (int) ($usage['output_tokens'] ?? 0),
                    tokensCacheRead: (int) ($usage['cache_read_input_tokens'] ?? 0),
                    tokensCacheCreation: (int) ($usage['cache_creation_input_tokens'] ?? 0),
                    errorMessage: "claude CLI: {$message} (the CLI discards the "
                        . 'over-cap response; no partial text survives)',
                    costUsd: isset($decoded['total_cost_usd'])
                        ? (float) $decoded['total_cost_usd'] : null,
                );
            }

            // A usage-limit answer will succeed later; a bad flag will not.
            $transient = stripos($message, 'rate limit') !== false
                || stripos($message, 'overloaded') !== false
                || stripos($message, 'usage limit') !== false;
            throw $transient
                ? new LLMTransientError("claude CLI: {$message}")
                : new LLMPermanentError("claude CLI (exit {$exit}): {$message}");
        }

        return new LLMResponse(
            stopReason: 'end_turn',
            contentBlocks: [['type' => 'text', 'text' => (string) ($decoded['result'] ?? '')]],
            tokensInput: (int) ($usage['input_tokens'] ?? 0),
            tokensOutput: (int) ($usage['output_tokens'] ?? 0),
            tokensCacheRead: (int) ($usage['cache_read_input_tokens'] ?? 0),
            tokensCacheCreation: (int) ($usage['cache_creation_input_tokens'] ?? 0),
            // `.total_cost_usd` is the third field the header names as what makes
            // a real LLMResponse possible — and until 2026-08-12 it was named and
            // then dropped on the floor. Carried now; Runner surfaces it on the
            // per-call agent_message audit row.
            costUsd: isset($decoded['total_cost_usd'])
                ? (float) $decoded['total_cost_usd'] : null,
        );
    }

    /**
     * Roles kept, because a transcript that loses who said what is not a
     * transcript. The CLI has no multi-turn flag in `--print` mode, so the
     * thread is rendered as text and labelled.
     *
     * @param list<Message> $messages
     */
    private function fold(array $messages): string
    {
        $parts = [];
        foreach ($messages as $m) {
            $role = strtoupper($m->role);
            $text = $this->textOf($m->content);
            if (trim($text) === '') {
                continue;
            }
            $parts[] = count($messages) === 1 ? $text : "[{$role}]\n{$text}";
        }
        return implode("\n\n", $parts);
    }

    /**
     * The text inside a message's CONTENT BLOCKS.
     *
     * `Message::$content` is a list of blocks (`{type: text|tool_result|…}`),
     * not a string — a live probe caught this adapter casting the array
     * straight to a string on its first run, which PHP would have rendered as
     * the word "Array" and sent to the model as the prompt.
     *
     * A `tool_result` block reaching here is a caller mistake rather than a
     * shape to render: this backend refuses tools outright (see `send()`), so a
     * result for a call it never made cannot be answered and is dropped
     * loudly-by-absence — the text folds to empty and `send()` refuses.
     *
     * @param list<array<string,mixed>> $blocks
     */
    private function textOf(array $blocks): string
    {
        $out = [];
        foreach ($blocks as $b) {
            if (is_array($b) && ($b['type'] ?? null) === 'text') {
                $out[] = (string) ($b['text'] ?? '');
            }
        }
        return implode("\n", $out);
    }

    /**
     * Run it without a shell.
     *
     * `proc_open` with an argv ARRAY, so nothing in a prompt is ever parsed as
     * shell syntax. `pulse-run-agent.sh` reaches the same conclusion by hand
     * (its comment at line 234 is about safe-escaping the task prompt); an
     * adapter that built a command string would be re-opening that hole in a
     * language with a better answer available.
     *
     * @param list<string>          $argv
     * @param array<string,string>  $envOverride merged over the inherited env —
     *        proc_open's env argument REPLACES the environment wholesale, and the
     *        CLI needs HOME (its config + the operator's session) and PATH, so a
     *        bare override array would break auth in a way that reads as a model
     *        error.
     * @return array{0:int,1:string,2:string}
     */
    private function run(array $argv, array $envOverride = []): array
    {
        $descriptors = [1 => ['pipe', 'w'], 2 => ['pipe', 'w']];
        $env = $envOverride === [] ? null : array_merge(getenv(), $envOverride);
        $proc = proc_open($argv, $descriptors, $pipes, null, $env);
        if (!is_resource($proc)) {
            throw new LLMTransientError("could not start '{$this->binary}'");
        }

        stream_set_blocking($pipes[1], false);
        stream_set_blocking($pipes[2], false);
        $stdout = '';
        $stderr = '';
        $deadline = time() + $this->timeoutS;

        while (true) {
            $stdout .= stream_get_contents($pipes[1]);
            $stderr .= stream_get_contents($pipes[2]);
            $status = proc_get_status($proc);
            if (!$status['running']) {
                break;
            }
            if (time() > $deadline) {
                proc_terminate($proc, 9);
                fclose($pipes[1]);
                fclose($pipes[2]);
                proc_close($proc);
                throw new LLMTransientError(sprintf(
                    'claude CLI exceeded %ds and was killed', $this->timeoutS
                ));
            }
            usleep(100_000);
        }

        $stdout .= stream_get_contents($pipes[1]);
        $stderr .= stream_get_contents($pipes[2]);
        fclose($pipes[1]);
        fclose($pipes[2]);
        // proc_close's return is -1 once proc_get_status has reaped the child,
        // so the exit code is taken from the status read above.
        proc_close($proc);

        return [(int) ($status['exitcode'] ?? 0), $stdout, $stderr];
    }
}
