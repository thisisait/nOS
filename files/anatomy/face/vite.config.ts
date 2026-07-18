/// <reference types="vitest/config" />
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	test: {
		// Unit tests co-locate as *.test.ts / *.spec.ts. Pure-logic modules
		// (contracts, filename rules, window math) run in node.
		include: ['src/**/*.{test,spec}.{js,ts}'],
		environment: 'node'
	}
});
