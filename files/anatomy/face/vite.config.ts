/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
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
