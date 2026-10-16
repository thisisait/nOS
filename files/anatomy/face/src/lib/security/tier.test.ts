import { describe, it, expect } from 'vitest';
import { canReadTable, canWriteTables } from './tier';

describe('tier · canWriteTables', () => {
	it('grants write to manager+ tiers', () => {
		expect(canWriteTables(['nos-admins'])).toBe(true);
		expect(canWriteTables(['nos-providers'])).toBe(true);
		expect(canWriteTables(['nos-managers', 'nos-users'])).toBe(true);
	});
	it('denies users/guests/empty', () => {
		expect(canWriteTables(['nos-users'])).toBe(false);
		expect(canWriteTables(['nos-guests'])).toBe(false);
		expect(canWriteTables([])).toBe(false);
		expect(canWriteTables(undefined)).toBe(false);
	});
	it('is case-insensitive + trims', () => {
		expect(canWriteTables([' NOS-Admins '])).toBe(true);
	});
});

describe('tier · canReadTable', () => {
	it('denies guests (and users) on tier-managers', () => {
		expect(canReadTable('tier-managers', ['nos-guests'])).toBe(false);
		expect(canReadTable('tier-managers', ['nos-users'])).toBe(false);
	});
	it('grants managers (and admins) on tier-managers', () => {
		expect(canReadTable('tier-managers', ['nos-managers'])).toBe(true);
		expect(canReadTable('tier-managers', ['nos-admins'])).toBe(true);
		expect(canReadTable('tier-managers', [' NOS-Managers '])).toBe(true);
	});
	it('denies unknown / missing visibility', () => {
		expect(canReadTable('tier-admins', ['nos-admins'])).toBe(false);
		expect(canReadTable('nope', ['nos-managers'])).toBe(false);
		expect(canReadTable(undefined, ['nos-managers'])).toBe(false);
		expect(canReadTable('', ['nos-managers'])).toBe(false);
	});
});

// Septum: device*, caddy-sessions and engram are private. KEAP's contract reads
// private as owner + admin (rank 1 = nos-admins/nos-providers), so the operator
// reads a seeder-owned private table without an explicit share; a manager does not.
describe('tier · canReadTable private', () => {
	it('grants tier-1 admins, denies managers and below', () => {
		expect(canReadTable('private', ['nos-admins'])).toBe(true);
		expect(canReadTable('private', ['nos-providers'])).toBe(true);
		expect(canReadTable('private', ['nos-managers'])).toBe(false);
		expect(canReadTable('private', ['nos-users'])).toBe(false);
	});
});

// Operator ruling 2026-10-16: "if it creates it, it must read it". KEAP reads
// private as owner + admin; face must not be stricter than the door it fronts.
describe('tier · canReadTable owner', () => {
	const me = { uid: 'alice', ownerId: 'user:alice' };
	it('lets the owner read their private table', () => {
		expect(canReadTable('private', ['nos-managers'], me)).toBe(true);
		expect(canReadTable('private', ['nos-users'], { uid: 'alice', ownerId: 'alice' })).toBe(true);
	});
	it('denies a non-owner non-admin', () => {
		expect(canReadTable('private', ['nos-managers'], { uid: 'bob', ownerId: 'user:alice' })).toBe(
			false
		);
		expect(canReadTable('private', ['nos-managers'], { uid: 'bob' })).toBe(false);
		expect(canReadTable('private', ['nos-managers'], { uid: '', ownerId: 'user:' })).toBe(false);
	});
	it('keeps admin access', () => {
		expect(canReadTable('private', ['nos-admins'], { uid: 'bob', ownerId: 'user:alice' })).toBe(
			true
		);
	});
	it('does not widen other grades for an owner', () => {
		expect(canReadTable('tier-managers', ['nos-users'], me)).toBe(false);
	});
});
