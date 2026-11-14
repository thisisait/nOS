/// <reference types="vitest/config" />
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		// SvelteKit 3 reads its config here (svelte.config.js is refused). adapter-node: the shell runs
		// as a small Node server (the BFF) in the `nos/face` container, bound to PORT (5090). The BFF
		// holds the Bone/Wing/KEAP tokens; the default same-origin CSRF check stays on.
		sveltekit({
			adapter: adapter(),
			preprocess: vitePreprocess(),
			// kit 3 dropped the built-in `$lib`; the alias keeps the 417 imports as they are.
			alias: { $lib: 'src/lib' }
		})
	],
	// Tests only: a happy-dom file (Iris.test.ts) runs in vitest's client environment, which
	// otherwise resolves svelte's server runtime, where mount() throws. The build is untouched.
	...(process.env.VITEST
		? { environments: { client: { resolve: { conditions: ['browser'] } } } }
		: {}),
	test: {
		// Unit tests co-locate as *.test.ts / *.spec.ts. Pure-logic modules
		// (contracts, filename rules, window math) run in node.
		include: ['src/**/*.{test,spec}.{js,ts}'],
		environment: 'node',
		// Iris's fmt.ts reads navigator.language: tests read in en whatever the host's LANG is.
		setupFiles: ['src/lib/iris/test-locale.ts']
	}
});
