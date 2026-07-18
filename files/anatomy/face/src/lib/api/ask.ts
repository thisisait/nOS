/** Command-palette LLM client → BFF /bff/ask (host-local Ollama). */
import { bffPost } from './client';

export interface AskResult {
	configured: boolean;
	model?: string;
	answer?: string;
	note?: string;
}

export async function ask(prompt: string): Promise<AskResult> {
	return bffPost<AskResult>('/bff/ask', { prompt });
}
