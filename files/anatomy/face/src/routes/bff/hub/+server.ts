/** BFF · app catalog. Normalizes the Wing /hub/systems payload into HubApp[].
 *
 * Wing emits a full IT-inventory row per system — host daemons, backends, DBs,
 * and web apps alike — keyed by `id` (NOT `slug`) with a loopback `url` plus a
 * public `domain`/`domain_url`. The desktop only wants ENABLED services that
 * actually have a browser UI reachable at a public https origin, so we filter on
 * `has_web_ui` + `enabled` + a public URL and key off `id`. (Keying off `slug`
 * with the loopback `url` is why the dock used to come up empty.) */
import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { hubSystems } from '$lib/server/upstream';
import type { HubApp } from '$lib/contracts';

interface RawSystem {
	id?: string;
	slug?: string;
	title?: string;
	name?: string;
	icon?: string;
	url?: string;
	launch_url?: string;
	domain?: string;
	domain_url?: string;
	description?: string;
	tier?: number | string;
	rbac_tier?: string;
	has_web_ui?: number | boolean;
	enabled?: number | boolean;
	embed?: boolean | string;
}

/** Operator-declared embeddability from a hub_card: true/false explicit,
 *  undefined = attempt inline (cross-origin frame-blocks aren't JS-detectable). */
function mapEmbed(v: boolean | string | undefined): boolean | undefined {
	if (v === true || v === 'true') return true;
	if (v === false || v === 'false') return false;
	return undefined;
}

const truthy = (v: number | boolean | undefined): boolean => v === 1 || v === true;

/** A public browser origin for the service, or '' when it has none. */
function publicUrl(s: RawSystem): string {
	const u = s.domain_url ?? s.url ?? s.launch_url ?? '';
	return /^https?:\/\//.test(u) ? u : '';
}

/** Numeric RBAC tier: from a `tier-N` string, a bare number, else 3 (user). */
function tierOf(s: RawSystem): number {
	if (typeof s.tier === 'number') return s.tier;
	const m = /(\d)/.exec(s.rbac_tier ?? String(s.tier ?? ''));
	return m ? Number(m[1]) : 3;
}

/** Icon: an explicit hub_card glyph, else a single-letter monogram (the dock
 *  renders icons as escaped text, so a letter is a legible fallback). */
function iconOf(title: string, icon?: string): string {
	if (icon && icon.trim()) return icon.trim();
	const ch = title.trim().charAt(0).toUpperCase();
	return ch || '•';
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
		.map((s): HubApp | null => {
			const slug = s.id ?? s.slug;
			const url = publicUrl(s);
			// Only enabled, web-facing services with a reachable public origin.
			if (!slug || !truthy(s.has_web_ui) || !truthy(s.enabled) || !url) return null;
			const title = String(s.title ?? s.name ?? slug);
			return {
				slug: String(slug),
				title,
				icon: iconOf(title, s.icon),
				url,
				description: String(s.description ?? ''),
				tier: tierOf(s),
				embed: mapEmbed(s.embed)
			};
		})
		.filter((a): a is HubApp => a !== null);
	apps.sort((a, b) => a.title.localeCompare(b.title));
	return json({ apps });
};
