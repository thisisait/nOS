/// <reference types="vitest/config" />
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

// Iris (face/src/lib/iris), the face's tokens and ui/ primitives, borrowed by alias (they
// import nothing but svelte); $lib is the face's own alias, which the Iris files use.
// dedupe keeps one svelte runtime even if face/node_modules exists, and resolves the face's
// @xyflow/svelte import (Iris's canvas) from the pupil's own node_modules.
const face = fileURLToPath(new URL('../face/src', import.meta.url));

export default defineConfig({
	plugins: [svelte()],
	resolve: {
		alias: { $face: face, $lib: face + '/lib', $iris: face + '/lib/iris' },
		dedupe: ['svelte', '@xyflow/svelte']
	},
	server: { fs: { allow: ['.', face] } },
	// face/tsconfig.json extends a generated .svelte-kit file; never read it.
	esbuild: { tsconfigRaw: '{}' },
	build: { outDir: 'dist', emptyOutDir: true },
	test: { include: ['src/**/*.test.ts'], environment: 'node' }
});
