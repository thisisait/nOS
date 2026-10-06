import { describe, it, expect } from 'vitest';
import {
	AGENT_NAME,
	parseOpenBody,
	projectOpened,
	projectSession,
	projectSessionList
} from './sessions';

const ROW = {
	id: 7,
	uuid: '0b8e3c1a-1111-4222-8333-444455556666',
	agent_name: 'helper',
	agent_version: 1,
	status: 'idle',
	trigger: 'operator',
	actor_id: 'user:alice',
	trace_id: 'a'.repeat(32),
	model_uri: 'anthropic-claude',
	tokens_input: 10,
	result_json: '{"secret":"x"}',
	error_json: null,
	started_at: '2026-10-06T10:00:00Z',
	ended_at: '2026-10-06T10:01:00Z',
	stop_reason: 'end_turn',
	outcome_result: null
};

describe('session projection — an allow-list, not a proxy', () => {
	it('keeps exactly the declared fields', () => {
		expect(Object.keys(projectSession(ROW)!).sort()).toEqual(
			['agent', 'endedAt', 'outcome', 'startedAt', 'status', 'stopReason', 'uuid'].sort()
		);
	});
	it('drops a field upstream adds tomorrow', () => {
		const v = projectSession({ ...ROW, api_token: 'leak' }) as unknown as Record<string, unknown>;
		expect(JSON.stringify(v)).not.toContain('leak');
		expect(JSON.stringify(v)).not.toContain('secret');
		expect(JSON.stringify(v)).not.toContain('user:alice');
	});
	it('lists from {data}, skipping rows without a uuid', () => {
		expect(projectSessionList({ data: [ROW, { status: 'x' }] })).toHaveLength(1);
		expect(projectSessionList({})).toEqual([]);
	});
	it('the 202 carries uuid + status, not pid or actor', () => {
		expect(
			projectOpened({ session_uuid: ROW.uuid, status: 'starting', pid: 9, actor_id: 'user:alice' })
		).toEqual({ uuid: ROW.uuid, status: 'starting' });
		expect(projectOpened({})).toBeNull();
	});
});

describe('open body — exactly {prompt?}', () => {
	it('accepts empty and a prompt', () => {
		expect(parseOpenBody({})).toEqual({});
		expect(parseOpenBody({ prompt: 'hi' })).toEqual({ prompt: 'hi' });
	});
	it('refuses, not strips, anything that could name an identity or a credential', () => {
		for (const k of ['actor_id', 'uid', 'vault', 'agent']) {
			expect(typeof parseOpenBody({ prompt: 'hi', [k]: 'x' })).toBe('string');
		}
	});
	it('refuses a non-object, a non-string and an oversized prompt', () => {
		expect(typeof parseOpenBody(null)).toBe('string');
		expect(typeof parseOpenBody(['prompt'])).toBe('string');
		expect(typeof parseOpenBody({ prompt: 3 })).toBe('string');
		expect(typeof parseOpenBody({ prompt: 'x'.repeat(8001) })).toBe('string');
	});
	it('agent names cannot carry a path', () => {
		expect(AGENT_NAME.test('ops-triage')).toBe(true);
		for (const n of ['../x', 'a/b', '', 'A', 'a%2Fb']) expect(AGENT_NAME.test(n)).toBe(false);
	});
});
