// The header's model picker (W5): which option the select names, what it says, what a pick sends.
import type { ModelOption, ToThalamus } from './wire';

export const keyOf = (o: Pick<ModelOption, 'backend' | 'model'>) => `${o.backend} ${o.model}`;

/** The model, who processes the turns, and whether they leave the EU. */
export const labelOf = (o: ModelOption) => `${o.model} · ${o.processor} · ${o.transfers_outside_eu ? 'leaves the EU' : 'EU'}`;

/** The pick for `key`; null for the current one or a key serve did not offer. */
export function pickOf(options: ModelOption[], key: string): ToThalamus | null {
	const o = options.find((x) => keyOf(x) === key);
	return o && !o.current ? { t: 'model_pick', backend: o.backend, model: o.model } : null;
}
