/**
 * Every environment variable the BFF reads, declared: SvelteKit 3 hands the server only declared variables
 * (an undeclared `env.X` is undefined, whatever the container sets). All are private, read when the app
 * starts, and optional: a missing one keeps its reader's own fallback. FACE_EDGE_TOKEN is the edge-trust
 * secret (hooks.server.ts): undeclared, the hook would trust every caller.
 */
import { defineEnvVars } from '@sveltejs/kit/env';

const optional = { schema: (value: string | undefined) => value };

export const variables = defineEnvVars({
	BONE_LOOP_JUDGE_TOKEN: optional,
	FACE_EDGE_TOKEN: optional,
	FACE_EDGE_TOKEN_HEADER: optional,
	FACE_LAYOUT_REPIN: optional,
	KEAP_PROXY_SHARED_SECRET: optional,
	NOS_ASK_MODEL: optional,
	NOS_BONE_EVENTS_URL: optional,
	NOS_HUB_API_URL: optional,
	NOS_KEAP_EXPLORE_URL: optional,
	NOS_KEAP_TABLES_URL: optional,
	NOS_OLLAMA_URL: optional,
	NOS_THALAMUS_RELAY_ADDR: optional,
	NOS_VFS_API_TOKEN: optional,
	NOS_VFS_API_URL: optional,
	NOS_WING_API_URL: optional,
	NOS_WING_BFF_TOKEN: optional,
	PUPIL_FIXTURE: optional,
	THALAMUS_RELAY_SECRET: optional,
	WING_EVENTS_HMAC_SECRET: optional
});
