import type { Identity } from '$lib/contracts';

// See https://svelte.dev/docs/kit/types#app.d.ts
declare global {
	namespace App {
		interface Error {
			message: string;
		}
		interface Locals {
			/** The per-user identity the BFF derived from the edge-trusted
			 *  Authentik forward-auth headers. Never invented, never from the body. */
			identity: Identity;
		}
		interface PageData {
			identity: Identity;
		}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
