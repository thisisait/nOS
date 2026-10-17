// W5: the person picks Iris's model for the session in the header: a native select over the options
// serve offered (model_options), each with its processor and whether the turns leave the EU; a model
// under the recommended size carries a warn badge. Picking sends model_pick; nothing else does.
import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import ModelPicker from './ModelPicker.svelte';
import { keyOf, labelOf, pickOf } from './model';
import type { ModelOption } from './wire';

const big: ModelOption = { backend: 'ollama', model: 'qwen3:14b', processor: 'This host (on-device, Ollama)', transfers_outside_eu: false, current: true };
const small: ModelOption = { ...big, model: 'qwen3:4b', current: false, warning: "'qwen3:4b' has 4B parameters, below the 8B recommended" };
const eu: ModelOption = { backend: 'mistral-eu', model: 'mistral-large-latest', processor: 'Mistral AI SAS', transfers_outside_eu: false, current: false };
const away: ModelOption = { ...eu, backend: 'minimax', model: 'MiniMax-M2', processor: 'MiniMax', transfers_outside_eu: true };
// Ruling 2026-10-17: Iris on Anthropic's OpenAI-compatible row, offered by serve only when armed, keyed and gdpr_posture: none.
const claude: ModelOption = { ...eu, backend: 'anthropic-api', model: 'claude-haiku-5-5', processor: 'Anthropic PBC', transfers_outside_eu: true };

describe('the model picker', () => {
	it('names each option with its processor and whether it leaves the EU', () => {
		expect(labelOf(eu)).toBe('mistral-large-latest · Mistral AI SAS · EU');
		expect(labelOf(away)).toBe('MiniMax-M2 · MiniMax · leaves the EU');
	});

	it('a pick sends model_pick for that option; the current one or an unknown key sends nothing', () => {
		const all = [big, small, eu];
		expect(pickOf(all, keyOf(eu))).toEqual({ t: 'model_pick', backend: 'mistral-eu', model: 'mistral-large-latest' });
		expect(pickOf(all, keyOf(big))).toBeNull();
		expect(pickOf(all, 'nope')).toBeNull();
	});

	it('is a native select showing the current model, text only', () => {
		const h = render(ModelPicker, { props: { options: [big, small, eu], onpick: () => {} } }).body;
		expect(h).toContain('<select');
		for (const s of ['qwen3:14b', 'qwen3:4b', 'Mistral AI SAS']) expect(h).toContain(s);
		expect(h).not.toMatch(/class="warn[ "]/);
	});

	it('a current model under the recommended size carries the warn badge', () => {
		const h = render(ModelPicker, { props: { options: [{ ...big, current: false }, { ...small, current: true }], onpick: () => {} } }).body;
		expect(h).toMatch(/class="warn[ "][^>]*title="'qwen3:4b' has 4B parameters/);
	});

	it('an armed anthropic-api option says it leaves the EU, and a pick sends it', () => {
		expect(labelOf(claude)).toBe('claude-haiku-5-5 · Anthropic PBC · leaves the EU');
		const h = render(ModelPicker, { props: { options: [big, eu, claude], onpick: () => {} } }).body;
		expect(h).toContain('claude-haiku-5-5 · Anthropic PBC · leaves the EU');
		expect(pickOf([big, eu, claude], keyOf(claude))).toEqual({ t: 'model_pick', backend: 'anthropic-api', model: 'claude-haiku-5-5' });
	});

	it('under gdpr_posture standard serve leaves anthropic-api out, and the picker says why', () => {
		const why = "anthropic-api: 'anthropic-api' is not EU-resident and gdpr_posture is 'standard': a non-EU row serves only under gdpr_posture: none";
		const h = render(ModelPicker, { props: { options: [big, eu], refused: [why], onpick: () => {} } }).body;
		expect(h).not.toContain('<option value="anthropic-api');
		expect(h).toContain('not offered: anthropic-api');
		expect(h).toContain('gdpr_posture is');
	});
});
