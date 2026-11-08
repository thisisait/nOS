// Row iris-face-answers-questions: the face lists the agents' open questions and sends one
// answer each; what Wing decided is shown in its own words, a lost answer names the winner.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Questions from './Questions.svelte';
import { answer, fromWire, said } from './questions';
import type { Value } from './wire';

const rows: { [k: string]: Value }[] = [
	{
		uuid: 'q1',
		agent_name: 'conductor',
		prompt: 'Apply the upgrade?',
		expires_at: '2099-01-01T00:00:00Z'
	},
	{ uuid: '', agent_name: 'x', prompt: 'no id' },
	{ uuid: 'q3', agent_name: 'x', prompt: null }
];

describe('agents questions in the face', () => {
	it('a row without a uuid or a prompt is not a question', () => {
		expect(fromWire(rows)).toEqual([
			{
				uuid: 'q1',
				agent: 'conductor',
				prompt: 'Apply the upgrade?',
				expires: '2099-01-01T00:00:00Z'
			}
		]);
	});

	it('a blank answer sends nothing; a real one is trimmed', () => {
		expect(answer('q1', '   ')).toBeNull();
		expect(answer('q1', ' yes ')).toEqual({ t: 'answer', uuid: 'q1', answer: 'yes' });
	});

	it('a lost answer names the one that won', () => {
		expect(
			said({ t: 'answer_result', uuid: 'q1', outcome: 'lost', winning_answer: 'no' })
		).toContain('no won first');
		expect(
			said({ t: 'answer_result', uuid: 'q1', outcome: 'refused', why: 'not tier 1' })
		).toContain('not tier 1');
	});

	it('unread is not "none"', () => {
		const props = { results: {}, onanswer: () => {}, onrefresh: () => {} };
		expect(render(Questions, { props: { ...props, items: null } }).body).toContain('not read yet');
		expect(render(Questions, { props: { ...props, items: [] } }).body).toContain(
			'No agent is waiting'
		);
		const one = render(Questions, {
			props: { ...props, items: fromWire(rows), results: { q1: 'answered' } }
		}).body;
		expect(one).toContain('Apply the upgrade?');
		expect(one).toContain('answered');
	});
});
