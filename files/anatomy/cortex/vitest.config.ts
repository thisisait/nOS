import { defineConfig } from 'vitest/config';

/**
 * Lifted from KEAP v1.27.0 vitest.config.ts, narrowed to the ported surface.
 *
 * Unit tests only. SCOPED so vitest never picks up the Playwright specs under
 * e2e/ (those import @playwright/test and run against the built bundle via
 * `npm run test:e2e`). Keep the two suites disjoint.
 *
 * `knowledge/**\/*.test.mjs` is in the glob on purpose even though no such file
 * has been ported yet — KEAP's ontology-sot round-trip test is C2 scope. The
 * glob matching nothing is not a gate: the P-4 gate is the digest assertion in
 * server/onto1-agreement.test.ts, which IS a .ts file and IS collected.
 */
export default defineConfig({
	test: {
		include: ['server/**/*.test.ts', 'knowledge/**/*.test.mjs'],
		environment: 'node',
	},
});
