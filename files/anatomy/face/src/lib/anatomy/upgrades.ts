/**
 * Wing upgrades projection — the matrix, the planned queue and the applied history, read-only.
 *
 * An ALLOW-LIST, like the Pulse and Wing projections. Wing's matrix row carries `recipes[]` (every recipe
 * with its steps), `reset` and `reset_json`; a history item carries `raw_record_json` and its decoded
 * `record`; a planned row carries free-text `notes`. None of that leaves the server: a field is copied
 * only when it is named here. Every verb (queue, plan, promote, apply) stays in Wing.
 *
 * Pure — vitest runs it in node.
 */

export interface UpgradeSecurity {
	/** The remediation queue could not be read: UNKNOWN, never "no pending row". */
	unavailable: boolean;
	/** Pending security rows for the service. */
	pending: number;
	/** The version the service must reach, when a row names one. */
	floor: string | null;
}

export interface UpgradeRow {
	id: string;
	service: string;
	installed: string | null;
	installedClass: string;
	stable: string | null;
	stableClass: string;
	latest: string | null;
	latestClass: string;
	severity: string;
	/** The recipes are behind the running version: not "up to date". */
	aheadOfCatalog: boolean;
	recipeCount: number;
	nextRecipeId: string;
	coexistenceSupported: boolean;
	/** null = no pending security row for this service. */
	security: UpgradeSecurity | null;
}

export interface PlannedRow {
	service: string;
	recipeId: string;
	status: string;
	targetVersion: string | null;
	plannedAt: string | null;
}

export interface HistoryRow {
	service: string;
	recipeId: string;
	fromVersion: string | null;
	toVersion: string | null;
	appliedAt: string | null;
	success: boolean;
	rolledBack: boolean;
}

export interface UpgradesSnapshot {
	services: UpgradeRow[];
	planned: PlannedRow[];
	history: HistoryRow[];
}

type Raw = Record<string, unknown>;

const str = (v: unknown): string | null => (typeof v === 'string' && v !== '' ? v : null);
const text = (v: unknown): string => str(v) ?? '';
const rows = (v: unknown): Raw[] =>
	Array.isArray(v) ? v.filter((x): x is Raw => typeof x === 'object' && x !== null) : [];

function security(v: unknown): UpgradeSecurity | null {
	if (typeof v !== 'object' || v === null) return null;
	const s = v as Raw;
	if (s.unavailable === true) return { unavailable: true, pending: 0, floor: null };
	return {
		unavailable: false,
		pending: Array.isArray(s.pending_ids) ? s.pending_ids.length : 0,
		floor: str(s.floor)
	};
}

/** The three Wing answers (`{services}`, `{planned}`, `{items}`) as the view's snapshot. A missing or
 *  misshapen list is an empty one here; the route reports an upstream failure itself. */
export function projectUpgrades(
	matrix: unknown,
	planned: unknown,
	history: unknown
): UpgradesSnapshot {
	const m = (matrix ?? {}) as Raw;
	const p = (planned ?? {}) as Raw;
	const h = (history ?? {}) as Raw;
	return {
		services: rows(m.services).map((r) => ({
			id: text(r.id),
			service: text(r.service),
			installed: str(r.installed),
			installedClass: text(r.installed_class) || 'unknown',
			stable: str(r.stable),
			stableClass: text(r.stable_class) || 'unknown',
			latest: str(r.latest),
			latestClass: text(r.latest_class) || 'unknown',
			severity: text(r.severity) || 'unknown',
			aheadOfCatalog: r.ahead_of_catalog === true,
			recipeCount: typeof r.recipe_count === 'number' ? r.recipe_count : 0,
			nextRecipeId: text(r.next_recipe_id),
			coexistenceSupported: r.coexistence_supported === true,
			security: security(r.security)
		})),
		planned: rows(p.planned).map((r) => ({
			service: text(r.service),
			recipeId: text(r.recipe_id),
			status: text(r.status),
			targetVersion: str(r.target_version),
			plannedAt: str(r.planned_at)
		})),
		history: rows(h.items).map((r) => ({
			service: text(r.service),
			recipeId: text(r.recipe_id),
			fromVersion: str(r.from_version),
			toVersion: str(r.to_version),
			appliedAt: str(r.applied_at),
			success: r.success === 1 || r.success === true,
			rolledBack: r.rolled_back === 1 || r.rolled_back === true
		}))
	};
}
