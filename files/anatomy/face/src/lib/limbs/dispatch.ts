/**
 * Limb dispatch: an Act runs only through a declared (app, action) pair whose
 * params pass the spec. A writes:true Act arrives only after the person approved
 * the card — the thalamus holds that ledger and is the only Act sender (the BFF
 * stream). Every failure is an Acted{ok:false}, never a throw.
 */
import { faceApps } from '$lib/apps/native/registry';
import { DESKTOP, desktopLimbs } from './desktop';
import type { Act, Acted, Limb, LimbDecl, ParamSpec } from './types';

function decls(): Array<[string, LimbDecl]> {
	return [
		...desktopLimbs.map((l): [string, LimbDecl] => [DESKTOP, l]),
		...faceApps().flatMap((a) => (a.limbs ?? []).map((l): [string, LimbDecl] => [a.slug, l]))
	];
}

/** Every limb the face declares, as sent on the wire (no handlers). */
export function declaredLimbs(): Limb[] {
	return decls().map(([app, { action, params, writes, says }]) => ({
		app,
		action,
		params,
		writes,
		says
	}));
}

function badParam(spec: Record<string, ParamSpec>, params: Record<string, unknown>): string | null {
	for (const k of Object.keys(params)) if (!Object.hasOwn(spec, k)) return `unknown param ${k}`;
	for (const [k, s] of Object.entries(spec)) {
		const v = params[k];
		if (v === undefined) {
			if (s.required) return `missing param ${k}`;
			continue;
		}
		if (s.type === 'enum' ? !s.values.includes(v as string) : typeof v !== s.type)
			return `bad param ${k}`;
	}
	return null;
}

export async function dispatch(act: Act): Promise<Acted> {
	const no = (reason: string): Acted => ({ act: act.act, ok: false, reason });
	const limb = decls().find(([app, l]) => app === act.app && l.action === act.action)?.[1];
	if (!limb) return no(`undeclared ${act.app}.${act.action}`);
	const params = act.params ?? {};
	const bad = badParam(limb.params, params);
	if (bad) return no(bad);
	if (!limb.run) return no('no handler');
	try {
		return { act: act.act, ok: true, result: await limb.run(params) };
	} catch (e) {
		return no(e instanceof Error ? e.message : String(e));
	}
}
