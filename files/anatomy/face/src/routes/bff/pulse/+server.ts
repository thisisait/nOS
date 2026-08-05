/** BFF · Anatomy → Pulse view. READ-ONLY, Tier-1 only.
 *
 * Exports GET and nothing else. SvelteKit answers 405 for a method with no
 * exported handler, so "read-only" here is a property of the module's shape
 * rather than a discipline someone has to remember — there is no POST/PUT/
 * PATCH/DELETE handler to reach.
 *
 * The response is a PROJECTION, never a proxy: Wing returns each job's env
 * block verbatim and on this estate that is 57 live credentials. See
 * `$lib/anatomy/pulse` for the allow-list and the reasoning.
 *
 * Three failure modes, deliberately distinguished — an observability surface
 * that renders "unreachable" the same as "nothing is wrong" is the defect it
 * was built to catch:
 *   configured:false  the Wing API token is not wired (a deployment fact)
 *   error:<message>   Wing answered, badly (an upstream fact)
 *   jobs:[]           Wing answered fine and there are genuinely no jobs
 */
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { pulseJobs, pulseRunSummary, pulseRuns, wingApiConfigured } from '$lib/server/upstream';
import { projectSnapshot } from '$lib/anatomy/pulse';
import { canViewAnatomy } from '$lib/security/tier';

export const GET: RequestHandler = async ({ locals, url }) => {
	// Gate on the edge-trusted identity, never on anything the client sends.
	if (!canViewAnatomy(locals.identity?.groups)) {
		throw error(403, 'The Anatomy view requires the admin tier.');
	}

	if (!wingApiConfigured()) {
		// NOT an empty list. The operator must be able to tell "nothing is
		// scheduled" from "this view was never wired up".
		return json({
			configured: false,
			note: 'NOS_WING_API_TOKEN is not set on the face container, so the Pulse API cannot be read. Nothing was checked.'
		});
	}

	// A single job's run history, for the detail pane.
	const jobId = url.searchParams.get('job_id');
	if (jobId) {
		try {
			const runs = (await pulseRuns(jobId, 25)) as { runs?: unknown[] };
			return json({ configured: true, jobId, runs: runs.runs ?? [] });
		} catch (e) {
			return json({
				configured: true,
				jobId,
				runs: [],
				error: e instanceof Error ? e.message : 'Wing did not answer'
			});
		}
	}

	try {
		// Sequential rather than Promise.all: two calls to the same loopback
		// service, where the second is meaningless without the first.
		const jobs = await pulseJobs();
		const summary = await pulseRunSummary();
		return json({ configured: true, ...projectSnapshot(jobs, summary) });
	} catch (e) {
		return json({
			configured: true,
			error: e instanceof Error ? e.message : 'Wing did not answer',
			jobs: [],
			counts: { never: 0, failing: 0, overdue: 0, running: 0, ok: 0, paused: 0, total: 0 }
		});
	}
};
