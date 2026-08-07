/**
 * Ring model — the run screen's radial figure, shaped by the operator's
 * refinement (2026-08-06): THE SPOKES ARE EXECUTIONS, NOT WORKERS, and each
 * finding opens another ring.
 *
 *   ring 0  the run          a gate set, a scan, a night, a proposal
 *   ring 1  its units        judges in the set / components in a batch
 *   ring 2  findings per unit
 *   ring 3  what each finding SPAWNED (a queue row, a roadmap row, a sub-run)
 *
 * Measured ring sizes on this estate run 5 (gate set `full`) to 125 (the
 * contradiction scan's pairs); both are the same component and neither is
 * padded — a node that exists for the picture poisons the LLM-readability
 * deliverable this figure shares data with.
 *
 * THE THREE STATES. `unjudged` is a first-class state, visually distinct from
 * both verdicts, because a denominator's gap is the finding: the contradiction
 * scan compared 125 pairs and SKIPPED 100 ("Skips are not agreements"), a
 * judge can return INDETERMINATE, a scan component's container can be absent.
 * In a list that fact is a footer; on a ring it is unlit spokes.
 *
 * TWO INVARIANTS, enforced here rather than hoped for downstream:
 *   1. The arc is driven by the RECORDED count. If a run says 125 and only 25
 *      child rows exist, the other 100 render as `unaccounted` spokes — the
 *      gap is rendered, never normalised away.
 *   2. Depth is bounded by data. `ring()` refuses an empty ring: a level with
 *      nothing on it is a claim that there was a level.
 *
 * Pure — no Svelte, no fetch — so vitest runs it in node.
 */

export type SpokeState = 'good' | 'bad' | 'unjudged';

export interface Spoke {
	id: string;
	label: string;
	state: SpokeState;
	/** Why the spoke is in its state — a judge's `reason`, a skip's cause.
	 *  Mandatory for `unjudged`: an unexplained non-judgement is not renderable
	 *  as anything but suspicion, so the model demands the explanation. */
	reason?: string;
	/** The next ring down: what THIS spoke opened. Absent when it opened
	 *  nothing — never an empty ring. */
	child?: Ring;
}

export interface Ring {
	label: string;
	/** The count the run RECORDED — its own statement of scope. */
	declared: number;
	/** Spokes for which rows exist. May be shorter than `declared`. */
	spokes: Spoke[];
	/** declared − spokes.length, floored at 0. Rendered as unlit spokes. */
	unaccounted: number;
}

/** Build a ring, enforcing both invariants. Returns null for an empty level —
 *  the caller then simply has no child, rather than a hollow claim. */
export function ring(label: string, declared: number, spokes: Spoke[]): Ring | null {
	if (declared <= 0 && spokes.length === 0) return null;
	for (const s of spokes) {
		if (s.state === 'unjudged' && !s.reason) {
			// An unjudged spoke with no reason would render as pure suspicion.
			// The model refuses to carry it silently instead of letting a
			// caller strip the explanation.
			throw new Error(`unjudged spoke ${s.id} carries no reason`);
		}
	}
	return {
		label,
		declared: Math.max(declared, spokes.length),
		spokes,
		unaccounted: Math.max(0, declared - spokes.length)
	};
}

export interface RingTally {
	good: number;
	bad: number;
	unjudged: number;
	unaccounted: number;
	declared: number;
}

export function tally(r: Ring): RingTally {
	const t: RingTally = {
		good: 0,
		bad: 0,
		unjudged: 0,
		unaccounted: r.unaccounted,
		declared: r.declared
	};
	for (const s of r.spokes) t[s.state] += 1;
	return t;
}

/** Geometry for one ring at a radius: each spoke an arc segment, unaccounted
 *  spokes get segments too (unlit). Angles in radians, from 12 o'clock. */
export interface SpokeArc {
	spoke: Spoke | null; // null = unaccounted (recorded but rowless)
	startAngle: number;
	endAngle: number;
}

export function arcs(r: Ring, gapFraction = 0.25): SpokeArc[] {
	const n = r.declared;
	if (n <= 0) return [];
	const seg = (Math.PI * 2) / n;
	const gap = seg * Math.min(0.9, gapFraction);
	const out: SpokeArc[] = [];
	for (let i = 0; i < n; i++) {
		const start = -Math.PI / 2 + i * seg;
		out.push({
			spoke: i < r.spokes.length ? r.spokes[i] : null,
			startAngle: start + gap / 2,
			endAngle: start + seg - gap / 2
		});
	}
	return out;
}

/** SVG path for one arc segment of a ring band. */
export function arcPath(
	cx: number,
	cy: number,
	rInner: number,
	rOuter: number,
	a0: number,
	a1: number
): string {
	const p = (r: number, a: number) => `${cx + r * Math.cos(a)} ${cy + r * Math.sin(a)}`;
	const large = a1 - a0 > Math.PI ? 1 : 0;
	return (
		`M ${p(rInner, a0)} ` +
		`A ${rInner} ${rInner} 0 ${large} 1 ${p(rInner, a1)} ` +
		`L ${p(rOuter, a1)} ` +
		`A ${rOuter} ${rOuter} 0 ${large} 0 ${p(rOuter, a0)} Z`
	);
}

// ── The loop ledger → rings (the one recursive instance live today) ────────

export interface LedgerProposal {
	uuid: string;
	weakness_id: string;
	intent_class: string;
	gate_set: string;
	attempt_n: number;
	created_at: string;
	id: number;
}

export interface LedgerJudgeRun {
	uuid: string;
	proposal_id: number | null;
	gate_set: string;
	judge_name: string;
	status: string;
	outcome: string | null;
	work_count: number | null;
	min_work: number | null;
	reason: string | null;
	started_at: string;
}

export interface LedgerVerdict {
	uuid: string;
	proposal_id: number | null;
	gate_set: string;
	result: string;
	evidence: string;
	created_at: string;
}

/**
 * One verdict → ring 1 of judges. The DECLARED denominator is the gate set's
 * committed membership (state/judge-sets.yml via the anatomy graph), never
 * the row count: a judge that never got a row is `unaccounted`, visibly.
 */
export function verdictRing(
	v: LedgerVerdict,
	runs: LedgerJudgeRun[],
	declaredJudges: string[]
): Ring | null {
	let runUuids: string[] = [];
	try {
		const ev = JSON.parse(v.evidence) as { judge_runs?: string[] };
		runUuids = ev.judge_runs ?? [];
	} catch {
		runUuids = [];
	}
	const byUuid = new Map(runs.map((r) => [r.uuid, r]));
	const spokes: Spoke[] = runUuids
		.map((u) => byUuid.get(u))
		.filter((r): r is LedgerJudgeRun => r !== undefined)
		.map((r) => ({
			id: r.uuid,
			label: r.judge_name,
			state:
				r.outcome === 'pass'
					? ('good' as const)
					: r.outcome === 'fail'
						? ('bad' as const)
						: ('unjudged' as const),
			reason:
				r.outcome === 'pass' || r.outcome === 'fail'
					? (r.reason ?? undefined)
					: (r.reason ?? r.status ?? 'no outcome recorded'),
			child: undefined
		}));
	return ring(
		`${v.gate_set} → ${v.result}`,
		Math.max(declaredJudges.length, runUuids.length),
		spokes
	);
}

/** Where a judge run's work count sits against its own ratchet floor. */
export interface Headroom {
	/** Percent above the floor. Negative means below it. */
	pct: number;
	/** Close enough that ordinary growth would breach it. */
	tight: boolean;
	/** Bar fill, 0..100, on a scale 20% above the floor. */
	fillPct: number;
	/** Where the floor tick sits on that same scale. */
	tickPct: number;
}

/**
 * The ratchet as a proportion, not a verdict.
 *
 * `judges.py:1353` already refuses to call a below-floor run a pass — it
 * resolves INDETERMINATE. So this is NOT a correctness display; it is the
 * leading indicator for the one that is.
 *
 * WHY IT EARNS A PLACE: this estate's ratchets have decayed twice, both times
 * by GROWTH rather than by anyone lowering a floor. The suite grew from 2456
 * to 2788 while the floor sat at 2400, so a run that had lost 14% of its
 * collection still cleared — the same defect as a floor 12x too low, arrived
 * at from the other direction. A bar showing a pass sitting 1% above its own
 * floor makes the NEXT decay visible before it fires.
 *
 * The scale is the floor plus 20%, so the tick lands at a fixed position and
 * bars stay comparable across judges whose absolute counts differ by three
 * orders of magnitude (2 artifacts, 1489 files, 3014 tests). Clamped: a run at
 * ten times its floor should read "far above", not blow the row apart.
 *
 * `tight` at <= 5% is a judgement call, stated so it can be argued with — it
 * is roughly one release of suite growth, which is how both decays happened.
 */
export function headroom(work: number, floor: number): Headroom {
	if (!Number.isFinite(work) || !Number.isFinite(floor) || floor <= 0) {
		return { pct: 0, tight: false, fillPct: 0, tickPct: 0 };
	}
	const scale = floor * 1.2;
	return {
		pct: Math.round(((work - floor) / floor) * 100),
		tight: work <= floor * 1.05,
		fillPct: Math.max(0, Math.min(100, (work / scale) * 100)),
		tickPct: (floor / scale) * 100
	};
}
