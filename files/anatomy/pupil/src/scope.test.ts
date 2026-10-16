import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import ApprovalCard from './ApprovalCard.svelte';
import { forCommand } from './scope';

describe('/for says whom the person works for', () => {
	it('parses a client, personal, all, and refuses no one', () => {
		expect(forCommand('/for ACME s.r.o.')).toEqual({ client: 'ACME s.r.o.' });
		expect(forCommand('/for personal')).toBe('personal');
		expect(forCommand('/for all')).toBe('all');
		expect(forCommand('/for')).toBeNull();
		expect(forCommand('for acme please')).toBeUndefined();
		expect(forCommand('/format')).toBeUndefined();
	});

	it('the waiting card says the scope it was asked under', () => {
		const waiting = { approval: 'a', component: { kind: 'markdown' as const, props: { text: 'x' } } };
		const card = render(ApprovalCard, { props: { waiting, of: 1, whole: true, scope: 'ACME s.r.o.', onseen: () => {}, ondecide: () => {} } }).body;
		expect(card).toContain('asked for ACME s.r.o.');
		const none = render(ApprovalCard, { props: { waiting, of: 1, whole: true, onseen: () => {}, ondecide: () => {} } }).body;
		expect(none).not.toContain('asked for');
	});
});
