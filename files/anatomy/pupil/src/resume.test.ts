// A resumed session redraws its chat from serve's replay, and the workspace is the thalamus's once
// it holds one: the local file moves up once, when it holds none (iris-workspace-survives-restart).
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import { decide, seen } from './approvals';
import Message from './Message.svelte';
import { adopt, replayed } from './resume';
import type { Component, ToShell } from './wire';
import * as ws from './workspace';

const S = '0b6f6a1e-3c2d-4e5f-8a9b-0c1d2e3f4a5b';
const red: Component = { kind: 'red_status', props: { red_count: 1, reds: ['pulse job nightly'], hold_count: 0, holds: [] } };
const choice: Component = { kind: 'choice', props: { id: 'c-open', question: 'Which table?', options: [{ label: 'expenses' }, { label: 'todos' }], suggested: ['expenses'], multi: false } };
const asked = (approval: string): ToShell => ({ t: 'approval_request', session: S, approval, component: red });
const replay = (log: ToShell[], open: string[]): Extract<ToShell, { t: 'replay' }> => ({ t: 'replay', session: S, log, open });

describe('a replay redraws the chat', () => {
	const r = replayed(replay([
		{ t: 'said', session: S, text: 'close alpha' },
		asked('a-decided'),
		{ t: 'said', session: S, text: 'approve' },
		{ t: 'text', session: S, text: 'Approved: row r1 written.' },
		{ t: 'render', session: S, component: { ...choice, props: { ...choice.props, id: 'c-answered' } } },
		{ t: 'render', session: S, component: choice },
		asked('a-open'),
		{ t: 'refused', reason: 'an approval is waiting: decide it first' }
	], ['a-open', 'c-open']));

	it('the person\'s turns are theirs, the rest is the thalamus\'s, in order', () => {
		expect(r.log.map((e) => ('me' in e ? `me:${e.me}` : 'msg' in e ? e.msg.t : 'note'))).toEqual(
			['me:close alpha', 'approval_request', 'me:approve', 'text', 'render', 'render', 'refused']);
	});

	it('an open card waits to be decided once; a decided one is history', () => {
		expect(r.q.pending.map((w) => w.approval)).toEqual(['a-open']);
		const d = decide(seen(r.q, 'a-open'), 'a-open', 'approve');
		expect(d.send).toEqual({ t: 'approval_decision', approval: 'a-open', decision: 'approve', note: null });
		expect(decide(d.q, 'a-open', 'approve').send).toBeNull();
		expect(decide(seen(r.q, 'a-decided'), 'a-decided', 'approve').send).toBeNull();
	});

	it('only a choice still open is asked again', () => {
		expect(r.asking).toEqual(['c-open']);
	});

	it('every replayed line draws what it said', () => {
		const page = r.log.map((e) => ('msg' in e ? render(Message, { props: { msg: e.msg } }).body : '')).join(' ');
		for (const s of ['pulse job nightly', 'Approved: row r1 written.', 'Which table?', 'an approval is waiting'])
			expect(page).toContain(s);
	});

	it('an empty replay is an empty log', () => {
		const e = replayed(replay([], []));
		expect([e.log, e.q.pending, e.asking]).toEqual([[], [], []]);
	});
});

describe('the workspace is the thalamus\'s', () => {
	const local: ws.Layout = { ...ws.empty(), workspaces: [{ id: 'ws1', name: 'Local', widgets: [] }] };
	const held: ws.Layout = { ...ws.empty(), workspaces: [{ id: 'ws1', name: 'Held', widgets: [] }] };

	it('none held: the local layout moves up once, and stays', () => {
		expect(adopt(local, null)).toEqual({ send: { t: 'workspace_save', doc: local }, layout: null });
	});

	it('one held: it replaces the local one, which is sent nowhere', () => {
		expect(adopt(local, held)).toEqual({ send: null, layout: held });
	});
});
