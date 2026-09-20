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
