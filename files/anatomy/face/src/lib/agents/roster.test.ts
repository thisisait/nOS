// Row wing-inc2-agents-timeline: the roster is a projection (no models, scopes or PII classes),
// a broken agent keeps its error, and the audit verdict never reads ok unless Wing knows it is.
import { describe, expect, it } from 'vitest';
import { projectRoster } from './roster';
import { auditLine } from '$lib/anatomy/audit';

describe('the agents app', () => {
	it('the roster keeps what the list shows and nothing of the model or its scopes', () => {
		const agents = projectRoster({
			data: [
				{
					name: 'ops-triage',
					version: 3,
					description: 'Triage',
					model_primary: 'ollama://x',
					capability_scopes: ['wing.write'],
					pii_classification: 'none',
					has_outcome: true
				},
				{ name: 'broken', error: 'agent.yml: no model' },
				null,
				{ version: 1 }
			]
		});
		expect(agents).toEqual([
			{ name: 'ops-triage', version: 3, description: 'Triage', gated: true, error: null },
			{ name: 'broken', version: null, description: '', gated: false, error: 'agent.yml: no model' }
		]);
		expect(JSON.stringify(agents)).not.toMatch(/ollama|wing\.write|pii/);
	});

	it('the audit chain is ok only when Wing knows it is', () => {
		const v = {
			chain: 'on',
			known: true,
			ok: true,
			checked: null,
			verifiedAt: 't',
			note: null
		} as const;
		expect(auditLine(v).badge).toBe('audit chain intact');
		expect(auditLine({ ...v, ok: false }).badge).toBe('audit chain BROKEN');
		expect(auditLine({ ...v, known: false, ok: null }).tone).toBe('warn');
		expect(auditLine({ ...v, chain: 'off' }).badge).toBe('audit chain off');
		expect(auditLine({ ...v, chain: null }).badge).not.toContain('intact');
	});
});
