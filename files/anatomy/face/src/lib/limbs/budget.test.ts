/**
 * D3 prompt budget: the thalamus says at most 24 limbs in full (LIMBS_SAID in
 * serve.rs) with says cut to 80 chars, for a 9b local model. The built-in face
 * stays inside it, so a registry change is caught here, offline.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { _resetRegistry, registerBuiltinNativeApps } from '$lib/apps/native/registry';
import { declaredLimbs } from './dispatch';

beforeEach(() => {
	_resetRegistry();
	registerBuiltinNativeApps();
});

describe('limbs · prompt budget', () => {
	it('the built-in face declares at most 24 limbs', () => {
		expect(declaredLimbs().length).toBeLessThanOrEqual(24);
	});

	it('every says fits 80 chars', () => {
		const long = declaredLimbs().filter((l) => [...l.says].length > 80);
		expect(long.map((l) => `${l.app}.${l.action}`)).toEqual([]);
	});
});
