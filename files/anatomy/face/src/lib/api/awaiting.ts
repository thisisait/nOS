/** "Awaiting you" client (row face-app-awaiting): /bff/awaiting, Tier 1, read-only. */
import { bffGet } from './client';
import type { Awaiting } from '$lib/awaiting/project';

export function loadAwaiting(): Promise<Awaiting> {
	return bffGet<Awaiting>('/bff/awaiting');
}
