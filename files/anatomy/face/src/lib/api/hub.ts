/** App-catalog client — the Wing /hub/systems feed, the single app registry. */
import { bffGet } from './client';
import type { HubApp } from '$lib/contracts';

export async function hubApps(): Promise<HubApp[]> {
	const r = await bffGet<{ apps: HubApp[] }>('/bff/hub');
	return r.apps ?? [];
}
