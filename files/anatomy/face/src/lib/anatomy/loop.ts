/**
 * Loop projection — the run screen's data contract over Bone's ledger lists
 * (`GET /api/v1/loop/{proposals,judge_runs,verdicts}`, read scope).
 *
 * TWO LOCKS ON THE SAME DOOR, on purpose. Bone's `ledger.list_proposals`
 * excludes `diff_text` at the SQL column list; this projection additionally
 * refuses it (and any other undeclared field) by mapping onto an explicit
 * allow-list. A projection can only refuse what it knows about, so the source
 * exclusion is the real guarantee — this one exists so that a future Bone
 * regression (a `SELECT *` refactor) still cannot reach a browser.
 *
 * Pure — no server imports, no fetch — so vitest runs it in node.
 */
import type { LedgerProposal, LedgerJudgeRun, LedgerVerdict } from './rings';

/** Fields that must NEVER reach the browser even if upstream sends them. */
export const WITHHELD_LOOP_FIELDS = ['diff_text', 'sandbox_path', 'stdout_head'] as const;

export interface LoopSnapshot {
	proposals: LedgerProposal[];
	judgeRuns: LedgerJudgeRun[];
	verdicts: LedgerVerdict[];
	counts: { proposals: number; judgeRuns: number; verdicts: number };
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (v == null ? '' : String(v));
const strOrNull = (v: unknown): string | null => (v == null ? null : String(v));

export function projectLoop(
	proposalsPayload: unknown,
	runsPayload: unknown,
	verdictsPayload: unknown
): LoopSnapshot {
	const p = ((proposalsPayload ?? {}) as { proposals?: Record<string, unknown>[] }).proposals ?? [];
	const r = ((runsPayload ?? {}) as { judge_runs?: Record<string, unknown>[] }).judge_runs ?? [];
	const v = ((verdictsPayload ?? {}) as { verdicts?: Record<string, unknown>[] }).verdicts ?? [];

	const proposals: LedgerProposal[] = p.map((row) => ({
		id: num(row.id) ?? 0,
		uuid: str(row.uuid),
		weakness_id: str(row.weakness_id),
		intent_class: str(row.intent_class),
		gate_set: str(row.gate_set),
		attempt_n: num(row.attempt_n) ?? 1,
		created_at: str(row.created_at)
	}));
	const judgeRuns: LedgerJudgeRun[] = r.map((row) => ({
		uuid: str(row.uuid),
		proposal_id: num(row.proposal_id),
		gate_set: str(row.gate_set),
		judge_name: str(row.judge_name),
		status: str(row.status),
		outcome: strOrNull(row.outcome),
		work_count: num(row.work_count),
		min_work: num(row.min_work),
		reason: strOrNull(row.reason),
		started_at: str(row.started_at)
	}));
	const verdicts: LedgerVerdict[] = v.map((row) => ({
		uuid: str(row.uuid),
		proposal_id: num(row.proposal_id),
		gate_set: str(row.gate_set),
		result: str(row.result),
		evidence: str(row.evidence),
		created_at: str(row.created_at)
	}));
	return {
		proposals,
		judgeRuns,
		verdicts,
		counts: {
			proposals: proposals.length,
			judgeRuns: judgeRuns.length,
			verdicts: verdicts.length
		}
	};
}
