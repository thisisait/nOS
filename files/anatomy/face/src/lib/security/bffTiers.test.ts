// Row face-app-min-tier (layer 2 of three): every BFF route has a tier, and a tier-1 route
// refuses below it in its own code. Read from the route files, not from this table's word.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import { BFF_TIERS, SCOPE_ROUTES } from './bffTiers';
import { _resetRegistry, faceApps, registerBuiltinNativeApps } from '$lib/apps/native/registry';

const ROUTES = new URL('../../routes', import.meta.url).pathname;

function serverFiles(dir: string): string[] {
	return readdirSync(dir).flatMap((n) => {
		const p = join(dir, n);
		return statSync(p).isDirectory() ? serverFiles(p) : n === '+server.ts' ? [p] : [];
	});
}

const routes = serverFiles(join(ROUTES, 'bff')).map((p) => ({
	route: '/' + relative(ROUTES, p).replace(/\/\+server\.ts$/, ''),
	code: readFileSync(p, 'utf8')
}));

describe('the BFF route tiers', () => {
	it('every route has a tier, and every tier names a route', () => {
		expect(routes.length).toBeGreaterThan(10);
		expect(routes.map((r) => r.route).sort()).toEqual(Object.keys(BFF_TIERS).sort());
	});

	it('a tier-1 route refuses below it in its own code', () => {
		for (const r of routes.filter((x) => BFF_TIERS[x.route] === 1)) {
			expect(r.code, r.route).toMatch(/canViewAnatomy\(/);
			expect(r.code, r.route).toMatch(/error\(403/);
		}
	});

	it('every scope an app declares names known routes', () => {
		_resetRegistry();
		registerBuiltinNativeApps();
		for (const a of faceApps())
			for (const s of a.apiScopes ?? []) {
				expect(SCOPE_ROUTES[s], `${a.slug} declares scope ${s}`).toBeDefined();
				for (const r of SCOPE_ROUTES[s]) expect(BFF_TIERS[r], r).toBeDefined();
			}
	});
});
