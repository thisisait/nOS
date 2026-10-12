// Stub: the shape the eye vitest pins; the reducer lands in the next commit.
import type { Link, ToShell } from './wire';

export type State = 'disconnected' | 'idle' | 'listening' | 'thinking' | 'tool' | 'writing' | 'said' | 'refused';
export type View = { state: State | 'waiting'; tool: string | null };
export type Eye = { state: State; tool: string | null; prev: { state: State; tool: string | null }; seq: number };
export type Input =
	| { e: 'wire'; msg: ToShell }
	| { e: 'link'; state: Link['state'] }
	| { e: 'typing'; text: string }
	| { e: 'settle'; seq: number };

export const SETTLE_MS = { said: 0, refused: 0 };
export const eye = (): Eye => ({ state: 'idle', tool: null, prev: { state: 'idle', tool: null }, seq: 0 });
export const step = (x: Eye, _: Input): Eye => x;
export const look = (x: Eye, _pending: number): View => ({ state: x.state, tool: x.tool });
export const label = (v: View): string => v.state;
