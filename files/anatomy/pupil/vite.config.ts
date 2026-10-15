/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

// The face's tokens and ui/ primitives, borrowed by alias (they import nothing but
// svelte); dedupe keeps one svelte runtime even if face/node_modules exists.
const face = fileURLToPath(new URL('../face/src', import.meta.url));

export default defineConfig({
	plugins: [svelte()],
	resolve: {
		alias: { $face: face, $ui: `${face}/lib/components/ui` },
		dedupe: ['svelte']
	},
	server: { fs: { allow: ['.', face] } },
	// face/tsconfig.json extends a generated .svelte-kit file; never read it.
	esbuild: { tsconfigRaw: '{}' },
	build: { outDir: 'dist', emptyOutDir: true },
	test: { include: ['src/**/*.test.ts'], environment: 'node', setupFiles: ['src/test-locale.ts'] }
});
