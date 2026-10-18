/**
 * A limb's REQUEST to an app — `anatomy/focus.ts` generalised. Apps hold their
 * state in component-local `$state`, so a limb cannot call into them; it leaves
 * a request under the app's slug, and the app consumes and clears it in an
 * `$effect` (on mount too, so open-then-request has no race). The nonce makes
 * two identical requests two store values.
 */
import { writable } from 'svelte/store';

export interface LimbRequest {
	action: string;
	params: Record<string, unknown>;
	nonce: number;
}

export const requests = writable<Record<string, LimbRequest>>({});

let seq = 0;

export function request(slug: string, action: string, params: Record<string, unknown>): void {
	requests.update((r) => ({ ...r, [slug]: { action, params, nonce: ++seq } }));
}

/** Clear `slug`'s request once the app has acted on it. */
export function consumed(slug: string): void {
	requests.update((r) => {
		const rest = { ...r };
		delete rest[slug];
		return rest;
	});
}
