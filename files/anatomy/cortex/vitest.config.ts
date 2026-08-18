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
 * glob matching nothing is not a gate: the P-4 hard gate is
 * server/onto1-digest.test.ts, which IS a .ts file and IS collected, and which
 * also shells out to knowledge/onto1-conformance.mjs so the six fixtures fail
 * `npm test` rather than waiting for someone to type `npm run conformance`.
 */
export default defineConfig({
	test: {
		include: ['server/**/*.test.ts', 'knowledge/**/*.test.mjs'],
		environment: 'node',
		// MEASURED 2026-08-18, after CI run 32142107402 went red on two
		// cortex-store tests and PASSED on a bare re-run. Not flake — a
		// margin. Both build a real store, and on this M-series Mac they
		// measure:
		//
		//     boots FTS-only …                4106 ms
		//     refuses a populated store …     4182 ms
		//
		// against vitest's 5000 ms default: an 18% margin, on a shared
		// runner that is slower than a laptop. CI reported 6696 ms and
		// 8877 ms. A timeout set that close to the measurement fails on
		// schedule, and a suite that goes red for reasons nobody acts on
		// teaches people to stop reading it — which costs more than the
		// two tests are worth.
		//
		// 20 s is 5x the measurement, not a number picked to make today
		// pass. If these tests grow past ~10 s, that is a real slowdown in
		// store construction and wants investigating, not another raise.
		testTimeout: 20_000,
	},
});
