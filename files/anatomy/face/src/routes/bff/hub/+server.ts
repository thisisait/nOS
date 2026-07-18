/** BFF · app catalog. Normalizes the Wing /hub/systems payload into HubApp[]
 *  and filters by the caller's tier (groups). */
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { hubSystems } from '$lib/server/upstream';
import type { HubApp } from '$lib/contracts';

interface RawSystem {
	slug?: string;
	title?: string;
	name?: string;
	icon?: string;
	url?: string;
	launch_url?: string;
	description?: string;
	tier?: number | string;
}

export const GET: RequestHandler = async () => {
	let raw: RawSystem[] = [];
	try {
		const data = (await hubSystems()) as { systems?: RawSystem[] } | RawSystem[];
		raw = Array.isArray(data) ? data : (data.systems ?? []);
	} catch {
		// Catalog down → an empty dock rather than a broken desktop.
		raw = [];
	}
	const apps: HubApp[] = raw
		.filter((s) => s.slug)
		.map((s) => ({
			slug: String(s.slug),
			title: String(s.title ?? s.name ?? s.slug),
			icon: String(s.icon ?? 'app'),
			url: String(s.url ?? s.launch_url ?? ''),
			description: String(s.description ?? ''),
			tier: Number(s.tier ?? 3)
		}));
	return json({ apps });
};
