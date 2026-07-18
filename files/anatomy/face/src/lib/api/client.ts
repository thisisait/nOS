/** Browser → BFF fetch wrapper. The BFF pins uid + holds tokens; the client
 *  only ever talks to same-origin /bff/* endpoints. */
export class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
	}
}

async function parse<T>(r: Response): Promise<T> {
	const text = await r.text();
	if (!r.ok) throw new ApiError(r.status, text || r.statusText);
	return (text ? JSON.parse(text) : {}) as T;
}

export async function bffGet<T>(path: string, params?: Record<string, string>): Promise<T> {
	const u = new URL(path, location.origin);
	if (params) for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
	return parse<T>(await fetch(u, { headers: { accept: 'application/json' } }));
}

export async function bffPost<T>(path: string, body: unknown): Promise<T> {
	return parse<T>(
		await fetch(path, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(body)
		})
	);
}
