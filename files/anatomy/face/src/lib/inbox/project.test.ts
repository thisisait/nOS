// Row wing-inc1-inbox-app: the BFF projects fixed fields, never proxies. A question never carries
// its reply token, the token's hash or its context; only `answered` reads as decided.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import { answerOutcome, projectNotifications, projectQuestions } from './project';

const wingQuestion = {
	id: 7,
	uuid: '7f3e2d1c-0b9a-4c8d-9e7f-6a5b4c3d2e1f',
	session_uuid: 's1',
	agent_name: 'conductor',
	kind: 'approval',
	prompt: 'Apply the nextcloud upgrade?',
	context_json: '{"secret":"x"}',
	options_json: '["yes","no"]',
	severity: 'high',
	status: 'open',
	reply_token: 'FAKE_plaintext_token',
	reply_token_sha: 'FAKE_sha_of_the_token',
	expires_at: '2099-01-01T00:00:00Z',
	default_on_expiry: 'no',
	created_at: '2026-11-08 08:00:00'
};

describe('the face inbox projection', () => {
	it('a question keeps the fields the person needs and none of the token', () => {
		const [q] = projectQuestions([wingQuestion]);
		expect(q).toEqual({
			uuid: wingQuestion.uuid,
			agent: 'conductor',
			kind: 'approval',
			prompt: 'Apply the nextcloud upgrade?',
			options: ['yes', 'no'],
			severity: 'high',
			created: '2026-11-08 08:00:00',
			expires: '2099-01-01T00:00:00Z',
			onExpiry: 'no'
		});
		const wire = JSON.stringify(projectQuestions([wingQuestion]));
		for (const leak of ['FAKE_plaintext_token', 'FAKE_sha_of_the_token', 'secret', 's1'])
			expect(wire).not.toContain(leak);
	});

	it('a row without a uuid or a prompt is not shown; bad options become a text field', () => {
		expect(projectQuestions([{ uuid: 'u' }, { prompt: 'p' }, 'x', null])).toEqual([]);
		expect(projectQuestions([{ ...wingQuestion, options_json: '[1,2]' }])[0].options).toBeNull();
		expect(projectQuestions('not a list')).toEqual([]);
	});

	it('a notification names who sent it', () => {
		const [n] = projectNotifications([
			{
				uuid: 'n1',
				severity: 'high',
				title: 'Gitleaks',
				body: 'b',
				origin_plugin: 'gitleaks',
				created_at: 't'
			}
		]);
		expect(n).toEqual({
			uuid: 'n1',
			severity: 'high',
			title: 'Gitleaks',
			body: 'b',
			created: 't',
			from: 'gitleaks'
		});
	});

	it('only a 200 ok is answered; a lost race names the winner', () => {
		expect(answerOutcome(200, { result: 'ok' })).toEqual({ outcome: 'answered' });
		expect(
			answerOutcome(409, { result: 'already', answer: 'yes', answered_by: 'user:bob' })
		).toEqual({
			outcome: 'lost',
			winning: 'yes',
			by: 'user:bob'
		});
		expect(answerOutcome(409, { result: 'expired', default_on_expiry: 'no' })).toEqual({
			outcome: 'expired',
			onExpiry: 'no'
		});
		expect(answerOutcome(403, { error: 'Tier 1 only' })).toEqual({
			outcome: 'refused',
			why: 'Tier 1 only'
		});
		expect(answerOutcome(200, {})).toEqual({ outcome: 'refused', why: 'Wing answered 200' });
	});
});

describe('the inbox app', () => {
	it('renders loading before the inbox answers, never an empty "all clear"', async () => {
		const { default: InboxApp } = await import('$lib/apps/native/InboxApp.svelte');
		const body = render(InboxApp).body;
		expect(body).toContain('loading');
		expect(body).not.toContain('No agent is waiting');
	});
});
