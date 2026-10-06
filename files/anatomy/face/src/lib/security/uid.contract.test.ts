// face half of the face<->Wing joint: uid.ts against the contract fixture bytes.
// Wing's half runs the same file (tests/anatomy/test_face_wing_contract.py).
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { slugifyUid, canonicalUid } from './uid';

const fx = JSON.parse(
	readFileSync(new URL('../../../../contracts/face-wing.fixture.json', import.meta.url), 'utf8')
) as {
	fold: { case: string; in: string; uid: string }[];
	claims: { case: string; username: string; email: string; raw_uid: string; uid: string }[];
};

describe('face-wing contract v1 — uid', () => {
	it.each(fx.fold)('fold: $case', (c) => expect(slugifyUid(c.in)).toBe(c.uid));
	it.each(fx.claims)('claims: $case', (c) =>
		expect(canonicalUid(c.username, c.email, c.raw_uid)).toBe(c.uid)
	);
	it('every uid the face emits is a fixed point Wing accepts', () => {
		for (const c of fx.claims) expect(slugifyUid(c.uid)).toBe(c.uid);
	});
});
