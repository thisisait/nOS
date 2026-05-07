<?php

declare(strict_types=1);

namespace App\AgentKit\Webhook;

use App\Model\AgentSubscriptionRepository;

/**
 * Outbound HMAC-signed webhook dispatcher. Mirrors Anthropic's Standard
 * Webhooks shape so external tooling already speaking that protocol works.
 *
 * Headers: X-Webhook-Id / X-Webhook-Timestamp / X-Webhook-Signature
 * Signature: HMAC-SHA256 over `<timestamp>.<raw_body>` -> base64, prefixed v1,
 *
 * Retry: 3 attempts with exponential backoff (200ms, 1s, 5s).
 * Auto-disable: 20 consecutive failures -> agent_subscriptions.enabled = 0.
 */
final class WebhookDispatcher
{
    private const RETRY_DELAYS_MS = [200, 1000, 5000];
    private const TIMEOUT_S = 5;
    private const AUTO_DISABLE_AFTER = 20;

    public function __construct(
        private readonly AgentSubscriptionRepository $subscriptions,
    ) {
    }

    /**
     * @param array<string, mixed> $data
     */
    public function fire(string $eventType, array $data): void
    {
        $subs = $this->subscriptions->listEnabledForEventType($eventType);
        if ($subs === []) {
            return;
        }

        $envelope = [
            'type' => 'event',
            'id' => 'event_' . bin2hex(random_bytes(12)),
            'created_at' => gmdate('c'),
            'data' => array_merge(['type' => $eventType], $data),
        ];
        $body = (string) json_encode($envelope, JSON_UNESCAPED_SLASHES);

        foreach ($subs as $sub) {
            $this->dispatchOne($sub, $body);
        }
    }

    /**
     * @param array{id: int, url: string, signing_secret: string} $sub
     */
    private function dispatchOne(array $sub, string $body): void
    {
        $webhookId = bin2hex(random_bytes(8));
        $timestamp = (string) time();
        $signature = base64_encode(hash_hmac(
            'sha256',
            $timestamp . '.' . $body,
            $sub['signing_secret'],
            true,
        ));

        $ok = false;
        foreach (self::RETRY_DELAYS_MS as $i => $delayMs) {
            if ($i > 0) {
                usleep($delayMs * 1000);
            }
            $status = $this->httpPost($sub['url'], $body, $webhookId, $timestamp, 'v1,' . $signature);
            if ($status >= 200 && $status < 300) {
                $ok = true;
                break;
            }
        }

        if ($ok) {
            $this->subscriptions->recordSuccess((int) $sub['id']);
        } else {
            $consecutiveFailures = $this->subscriptions->recordFailure((int) $sub['id']);
            if ($consecutiveFailures >= self::AUTO_DISABLE_AFTER) {
                $this->subscriptions->disable(
                    (int) $sub['id'],
                    "auto-disabled after {$consecutiveFailures} consecutive failures",
                );
            }
        }
    }

    private function httpPost(
        string $url,
        string $body,
        string $webhookId,
        string $timestamp,
        string $signature,
    ): int {
        $ch = curl_init($url);
        if ($ch === false) {
            return 0;
        }
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_HTTPHEADER => [
                'Content-Type: application/json',
                'X-Webhook-Id: ' . $webhookId,
                'X-Webhook-Timestamp: ' . $timestamp,
                'X-Webhook-Signature: ' . $signature,
                'User-Agent: nos-agentkit-webhook/1.0',
            ],
            CURLOPT_TIMEOUT => self::TIMEOUT_S,
            CURLOPT_FOLLOWLOCATION => false,
        ]);
        curl_exec($ch);
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        return $status;
    }
}
