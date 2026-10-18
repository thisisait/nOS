// A resumed session and the workspace the thalamus holds, as the pupil takes them
// (thalamus-shell.yml wire.replay, wire.workspace). Pure; App sends and draws.
import { asked, empty, type Queue } from './approvals';
import type { ToShell, ToThalamus } from './wire';
import { migrate, type Layout } from './workspace';

export type Entry = { me: string } | { msg: ToShell } | { note: string };

/** The chat a replay redraws: the person's turns as theirs, an open card waiting again, an open choice asked again. */
export function replayed(m: Extract<ToShell, { t: 'replay' }>): {
	log: Entry[];
	q: Queue;
	asking: string[];
} {
	let q = empty();
	const log: Entry[] = [];
	const asking: string[] = [];
	for (const e of m.log) {
		if (e.t === 'said') log.push({ me: e.text });
		else if (e.t === 'approval_request' && m.open.includes(e.approval)) q = asked(q, e);
		else {
			if (
				e.t === 'render' &&
				e.component.kind === 'choice' &&
				e.component.props.id &&
				m.open.includes(e.component.props.id)
			)
				asking.push(e.component.props.id);
			log.push({ msg: e });
		}
	}
	return { log, q, asking };
}

/** The thalamus's copy wins (a v2 one as v3); with none held, the local one goes up, once (it is held from then on). */
export const adopt = (
	local: Layout,
	doc: object | null
): { send: ToThalamus | null; layout: Layout | null } =>
	doc
		? { send: null, layout: migrate(doc as Layout) }
		: { send: { t: 'workspace_save', doc: local }, layout: null };
