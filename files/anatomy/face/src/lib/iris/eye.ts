// The eye's state: what the thalamus says it is doing (wire `activity`, text, refused),
// the link, and one local input — the person typing — which is labelled as local.
// Pure; the 600 ms / 1.5 s timers come back as `settle` carrying the seq they were set for.
// Waiting is not a state here: it is the approval queue (pending > 0) or an open choice
// (asking > 0), and it wins in look(). `loaded` is the thalamus's ModelState (null =
// unknown or remote); it only colours the idle mood, so it survives the link.
import type { Link, ToShell } from './wire';

export type State =
	'disconnected' | 'idle' | 'listening' | 'thinking' | 'tool' | 'writing' | 'said' | 'refused';
export type View = { state: State | 'waiting'; tool: string | null; loaded?: boolean | null };
type At = { state: State; tool: string | null };
/** `prev` is where a refusal settles; `seq` names the timer that may settle this state. */
export type Eye = At & { prev: At; seq: number; loaded: boolean | null };
export type Input =
	| { e: 'wire'; msg: ToShell }
	| { e: 'link'; state: Link['state'] }
	| { e: 'typing'; text: string }
	| { e: 'model'; loaded: boolean | null }
	| { e: 'settle'; seq: number };

export const SETTLE_MS = { said: 600, refused: 1500 };

const at = (state: State, tool: string | null = null): At => ({ state, tool });
const go = (x: Eye, to: At): Eye => ({ ...x, ...to });
/** A timed state: a new seq, so an older timer cannot settle it. */
const flash = (x: Eye, to: State, prev: At): Eye => ({ ...x, ...at(to), prev, seq: x.seq + 1 });

export const eye = (): Eye => ({ ...at('disconnected'), prev: at('idle'), seq: 0, loaded: null });

export function step(x: Eye, i: Input): Eye {
	if (i.e === 'model') return { ...x, loaded: i.loaded };
	if (i.e === 'link') return i.state === 'closed' ? go(x, at('disconnected')) : go(x, at('idle'));
	if (x.state === 'disconnected') return x;
	if (i.e === 'settle') {
		if (i.seq !== x.seq) return x;
		return x.state === 'said' ? go(x, at('idle')) : x.state === 'refused' ? go(x, x.prev) : x;
	}
	if (i.e === 'typing') {
		if (x.state === 'idle' && i.text.trim()) return go(x, at('listening'));
		return x.state === 'listening' && !i.text.trim() ? go(x, at('idle')) : x;
	}
	const m = i.msg;
	if (m.t === 'text') return flash(x, 'said', at('idle'));
	if (m.t === 'refused')
		return flash(
			x,
			'refused',
			x.state === 'refused' ? x.prev : x.state === 'said' ? at('idle') : at(x.state, x.tool)
		);
	if (m.t !== 'activity') return x;
	const p = m.phase;
	const to = typeof p === 'string' ? at(p) : at('tool', p.tool.name);
	// The flicker finishes first and settles where the wire now is; the turn-end idle
	// never cuts a said flash short (its own timer goes to idle).
	if (x.state === 'refused') return { ...x, prev: to };
	if (x.state === 'said' && to.state === 'idle') return x;
	return go(x, to);
}

export const look = (x: Eye, pending: number, asking = 0): View =>
	x.state === 'disconnected'
		? at('disconnected')
		: pending > 0
			? { state: 'waiting', tool: null }
			: asking > 0
				? { state: 'waiting', tool: 'choice' }
				: { ...at(x.state, x.tool), loaded: x.loaded };

/** What the bubble beside the eye says; `key` picks its colour and the icon's motion. */
export type Mood = { key: string; icon: string; text: string };
const M = (key: string, icon: string, text: string): Mood => ({ key, icon, text });

export function mood(v: View): Mood {
	switch (v.state) {
		case 'disconnected':
			return M('offline', '⛓️', 'offline');
		case 'idle':
			// Asleep = not in memory: the first turn loads it, so it will be slow.
			return v.loaded === true
				? M('ready', '🫡', 'ready')
				: v.loaded === false
					? M('asleep', '💤', 'model asleep')
					: M('ready', '', 'ready');
		case 'listening':
			return M('listening', '👂', 'listening (local)');
		case 'thinking':
			return M('thinking', '🧠', 'thinking');
		case 'tool':
			return M('working', '⛏️', v.tool ? `using ${v.tool}` : 'working');
		case 'writing':
			return M('writing', '✍️', 'writing');
		case 'waiting':
			return M('waiting', '✋', v.tool === 'choice' ? 'your turn: answer' : 'your turn: approve');
		case 'said':
			return M('said', '💬', 'said');
		case 'refused':
			return M('refused', '⚠️', 'refused');
	}
}
