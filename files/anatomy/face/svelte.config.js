import adapter from '@sveltejs/adapter-node';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// adapter-node: the shell runs as a small Node server (the BFF) inside the
		// `nos/face` container, bound to PORT (5090) — see roles/pazny.face.
		adapter: adapter()
		// The BFF holds the Bone/Wing/KEAP tokens; the browser never sees them.
		// SvelteKit's default same-origin CSRF check stays on (defense-in-depth
		// alongside the edge token).
	}
};

export default config;
