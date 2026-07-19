import { describe, it, expect } from 'vitest';
import { canWriteTables } from './tier';

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
