/** Per-user KV client (F1 recipe). Each app owns a namespace: `face.*` for the
 *  shell, `app.<name>` for utils. Values are small structured JSON (≤256 KB). */
import { bffGet, bffPost, ApiError } from './client';

export async function usGet<T>(ns: string, key: string): Promise<T | null> {
	try {
		const r = await bffGet<{ value: T }>('/bff/userstate', { ns, key });
		return r.value;
	} catch (e) {
		if (e instanceof ApiError && e.status === 404) return null;
		throw e;
	}
}

export async function usList<T>(ns: string): Promise<Array<{ key: string; value: T }>> {
	const r = await bffGet<{ items: Array<{ key: string; value: T }> }>('/bff/userstate', { ns });
	return r.items ?? [];
}

export async function usSet(ns: string, key: string, value: unknown): Promise<void> {
	await bffPost('/bff/userstate', { op: 'set', ns, key, value });
}

export async function usDelete(ns: string, key: string): Promise<void> {
	await bffPost('/bff/userstate', { op: 'delete', ns, key });
}
