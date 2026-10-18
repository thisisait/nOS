/**
 * Face limbs — a limb is a tool that acts (glossary). These are the wire
 * shapes of contract 7 (`Limbs`, `Act`, `Acted`); the contract bump mirrors
 * them 1:1, so change them only together with `contract/src/wire.rs`.
 */
export type ParamSpec =
	| { type: 'string' | 'number' | 'boolean'; required?: boolean }
	| { type: 'enum'; values: string[]; required?: boolean };

/** One declared (app, action) pair, as the face announces it. */
export interface Limb {
	app: string;
	action: string;
	params: Record<string, ParamSpec>;
	writes: boolean;
	says: string;
}

/** What an app (or the WM) declares: the wire Limb plus its local handler. */
export type LimbDecl = Omit<Limb, 'app'> & {
	run?: (params: Record<string, unknown>) => unknown | Promise<unknown>;
};

export interface Act {
	act: string;
	app: string;
	action: string;
	params: Record<string, unknown>;
}

export interface Acted {
	act: string;
	ok: boolean;
	result?: unknown;
	reason?: string;
}
