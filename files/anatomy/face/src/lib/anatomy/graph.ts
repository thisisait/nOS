/**
 * Graph projection — the definition screen's data contract over
 * `state/anatomy-graph.json` (imported at build time from the vendored copy
 * beside this module; `tools/anatomy-graph-gen.py` writes both and the
 * soundness gate refuses drift between them).
 *
 * WHY BUILD-TIME AND NOT AN ENDPOINT: the graph changes only when the repo
 * changes, and the repo reaches this host by converge — the same converge
 * that rebuilds the face. An endpoint would add a credential surface to serve
 * a file that cannot be fresher than the build that would serve it. The
 * screen therefore states the graph's OWN generation source instead of
 * pretending to be live.
 *
 * This module is a projection in the same sense as `pulse.ts`: it maps the
 * artifact onto explicit types and derived tables, and the view renders only
 * what is projected here. The artifact carries no secrets (the generator
 * withholds env blocks and full command paths at its own source), so unlike
 * the Pulse projection nothing is withheld — but additions are still a
 * deliberate edit here, not a consequence of the artifact growing a field.
 *
 * Pure — no server imports, no fetch — so vitest runs it in node.
 */

import type { Tone } from '$lib/components/ui';
import { SERVICE_LAYERS, type ServiceLayer } from '$lib/contracts';

export type NodeKind =
	| 'pulse'
	| 'judge'
	| 'gateset'
	| 'weakness'
	| 'daemon'
	| 'service'
	| 'resource'
	| 'repo'
	| 'tofu'
	| 'authentik'
	| 'table'
	| 'doctrine'
	| 'faceapp';

export type EdgeKind = 'data' | 'trigger' | 'temporal' | 'mutex' | 'governed_by';

export const NODE_KINDS: readonly NodeKind[] = [
	'pulse',
	'daemon',
	'judge',
	'gateset',
	'weakness',
	'resource',
	'repo',
	'tofu',
	'table',
	'doctrine',
	'faceapp',
	'authentik',
	'service'
] as const;

/** One glyph per node kind. Shared because two surfaces draw the same node
 *  ids (the Graph view's canvas and the desktop widget) and a second copy is
 *  how one node ends up wearing two icons. */
export const KIND_GLYPH: Record<NodeKind, string> = {
	pulse: '⏱',
	daemon: '⚙',
	judge: '⚖',
	gateset: '▦',
	weakness: '⚠',
	resource: '⛒',
	repo: '⎇',
	tofu: '⬡',
	table: '▤',
	doctrine: '§',
	faceapp: '🪟',
	authentik: '🛡',
	service: '▣'
};

/** Live pulse-job state → tone. A state NOT in this map has no tone: the
 *  caller renders it neutral and says it is unmeasured, never green. */
export const STATE_TONE: Record<string, Tone> = {
	failing: 'bad',
	never: 'warn',
	overdue: 'warn',
	running: 'info',
	findings: 'warn',
	ok: 'ok'
};

/** A node id shortened for a label: the kind prefix dropped, doctrine ids
 *  folded to `<doc> §<section>`, launchd labels stripped of the reverse-DNS
 *  prefix every one of them shares. The full id stays in the inspector and
 *  the tooltip — this shortens the LABEL, never the address. */
export function nodeLabel(id: string): string {
	const local = id.split(':').slice(1).join(':');
	if (id.startsWith('daemon:')) return local.replace(/^eu\.thisisait\.nos\./, '');
	if (id.startsWith('doctrine:')) {
		// "docs/idea/11-agentic-loop-contract.md#2.4" → "loop-contract §2.4"
		const [doc, section] = local.split('#');
		const base = (doc.split('/').pop() ?? doc).replace(/\.md$/, '');
		return `${base.replace(/^11-agentic-/, '')} §${section}`;
	}
	return local;
}

export interface GraphNode {
	id: string;
	kind: NodeKind;
	/** One-line body, present on every node (gated repo-side). */
	description: string;
	/** KEAP taxonomy anchor id, e.g. `02.02.08`. */
	anchor: string;
	source: string;
	/** service only — `declared` | `not-surveyed` | `no-manifest`. Lifted out
	 *  of `facts` because it must reach a PIXEL: the artifact published
	 *  `services_survey_not_surveyed: 39` and nothing rendered it, so on the
	 *  only canvas that draws this graph a measured root and a node nobody had
	 *  read were the same rectangle. */
	dependencySurvey: string | null;
	/** service only — a `ServiceLayer` from the genome's `axes` facet, or null
	 *  where the derivation refused to answer (docs/doctrine/layers.md §4.2).
	 *  The vocabulary is NOT spelled here: `state/genome/entity.schema.json`
	 *  declares it and `tools/anatomy-graph-gen.py::stamp_axes` refuses a value
	 *  outside it at compile time, so the cast below is a guarantee the
	 *  artifact carries rather than an assumption this module makes. */
	layer: ServiceLayer | null;
	/** Why `layer` is null. Never empty when `layer` is null. */
	layerWithheld: string | null;
	/** Kind-specific facts, rendered verbatim in the inspector. */
	facts: Record<string, unknown>;
}

export interface GraphEdge {
	from: string;
	to: string;
	kind: EdgeKind;
	via?: string;
	measured?: string;
	derived?: string;
	declared?: string;
	expects?: string;
	onFindings?: string;
	resource?: string;
	marginMin?: number;
	declaredMarginMin?: number;
	gapMin?: number;
	canInvert?: boolean;
	schedules?: string[];
	/** governed_by: how many distinct citing lines back this edge. */
	citations?: number;
}

export interface AnatomyGraph {
	counts: Record<string, number>;
	warnings: string[];
	nodes: GraphNode[];
	edges: GraphEdge[];
	byId: Map<string, GraphNode>;
}

/** Facts we lift to typed fields; everything else stays in `facts`. */
const LIFTED = new Set([
	'kind',
	'description',
	'anchor',
	'source',
	'dependency_survey',
	'layer',
	'layer_withheld'
]);

export function projectGraph(raw: unknown): AnatomyGraph {
	const g = (raw ?? {}) as {
		counts?: Record<string, number>;
		warnings?: string[];
		nodes?: Record<string, Record<string, unknown>>;
		edges?: Record<string, unknown>[];
	};
	const nodes: GraphNode[] = Object.entries(g.nodes ?? {}).map(([id, n]) => ({
		id,
		kind: String(n.kind ?? '') as NodeKind,
		description: String(n.description ?? ''),
		anchor: String(n.anchor ?? ''),
		source: String(n.source ?? ''),
		dependencySurvey: n.dependency_survey == null ? null : String(n.dependency_survey),
		layer: n.layer == null ? null : (String(n.layer) as ServiceLayer),
		layerWithheld: n.layer_withheld == null ? null : String(n.layer_withheld),
		facts: Object.fromEntries(Object.entries(n).filter(([k]) => !LIFTED.has(k)))
	}));
	const edges: GraphEdge[] = (g.edges ?? []).map((e) => ({
		from: String(e.from ?? ''),
		to: String(e.to ?? ''),
		kind: String(e.kind ?? '') as EdgeKind,
		via: e.via == null ? undefined : String(e.via),
		measured: e.measured == null ? undefined : String(e.measured),
		derived: e.derived == null ? undefined : String(e.derived),
		declared: e.declared == null ? undefined : String(e.declared),
		expects: e.expects == null ? undefined : String(e.expects),
		onFindings: e.on_findings == null ? undefined : String(e.on_findings),
		resource: e.resource == null ? undefined : String(e.resource),
		marginMin: typeof e.margin_min === 'number' ? e.margin_min : undefined,
		declaredMarginMin:
			typeof e.declared_margin_min === 'number' ? e.declared_margin_min : undefined,
		gapMin: typeof e.gap_min === 'number' ? e.gap_min : undefined,
		canInvert: typeof e.can_invert === 'boolean' ? e.can_invert : undefined,
		schedules: Array.isArray(e.schedules) ? e.schedules.map(String) : undefined,
		citations: typeof e.citations === 'number' ? e.citations : undefined
	}));
	return {
		counts: g.counts ?? {},
		warnings: (g.warnings ?? []).map(String),
		nodes,
		edges,
		byId: new Map(nodes.map((n) => [n.id, n]))
	};
}

/** What the service layer of this graph does NOT know, in one line.
 *
 *  WHY THIS EXISTS. The artifact published `services_survey_not_surveyed: 39`
 *  and `edges_service_dependency: 23`, and neither number reached a pixel: the
 *  kind chip read `service 63` while `connectedOnly` drew 20, and a service
 *  nobody had surveyed rendered as the same rectangle as a measured root. The
 *  producer counted the absence honestly and the rendering dropped it without
 *  a word, which is the calmer-than-the-data failure this estate keeps
 *  finding. So the remainder is a first-class projection, and the view renders
 *  it above the canvas rather than inside one node's inspector. */
export interface ServiceCoverage {
	services: number;
	surveyed: number;
	unsurveyed: number;
	noManifest: number;
	dependencyEdges: number;
	unenforcedEdges: number;
	layered: number;
	withheld: number;
	/** Rendered verbatim. Never "all clear" — when the survey is complete it
	 *  says so in words rather than by falling silent. */
	sentence: string;
}

export function serviceCoverage(graph: AnatomyGraph): ServiceCoverage {
	const c = graph.counts;
	const n = (k: string) => c[k] ?? 0;
	const cov: Omit<ServiceCoverage, 'sentence'> = {
		services: n('nodes_service'),
		surveyed: n('services_survey_declared'),
		unsurveyed: n('services_survey_not_surveyed'),
		noManifest: n('services_survey_no_manifest'),
		dependencyEdges: n('edges_service_dependency'),
		unenforcedEdges: n('edges_service_dependency_unenforced'),
		// Summed over the GENOME's layer vocabulary, not over four names typed
		// out here. This line was the fourth place the estate spelled L0…L3
		// (state/genome/entity.schema.json is now the only one), and a fifth
		// layer would have been counted by the compiler and dropped by the face.
		layered: SERVICE_LAYERS.reduce((sum, l) => sum + n(`services_layer_${l}`), 0),
		withheld: n('services_layer_withheld')
	};
	const gap = cov.unsurveyed + cov.noManifest;
	// A counts block with no services in it is UNMEASURED, not complete. The
	// first draft of this function reported `all 0 services surveyed` for an
	// artifact carrying nothing — the same failure it was written to fix, one
	// level up, and its own test caught it.
	const sentence =
		cov.services === 0
			? 'service coverage unmeasured — this graph carries no service counts'
			: gap === 0
				? `all ${cov.services} services surveyed · ${cov.dependencyEdges} dependency edges ` +
					`(${cov.unenforcedEdges} not backed by an auto-enable block) · layer derived for all`
				: `${cov.surveyed} of ${cov.services} services surveyed — ${gap} unread · ` +
					`${cov.dependencyEdges} dependency edges (${cov.unenforcedEdges} not backed by an ` +
					`auto-enable block) · layer derived for ${cov.layered}, WITHHELD for ${cov.withheld}`;
	return { ...cov, sentence };
}

/** The temporal-debt table — the reason the definition screen exists.
 *  `canInvert` rows first: those are edges whose own declared budgets already
 *  permit the ordering to flip. */
export interface TemporalDebtRow {
	from: string;
	to: string;
	schedules: string[];
	gapMin: number | null;
	marginMin: number | null;
	declaredMarginMin: number | null;
	canInvert: boolean;
	measured: string | null;
}

export function temporalDebt(graph: AnatomyGraph): TemporalDebtRow[] {
	return graph.edges
		.filter((e) => e.kind === 'temporal')
		.map((e) => ({
			from: e.from,
			to: e.to,
			schedules: e.schedules ?? [],
			gapMin: e.gapMin ?? null,
			marginMin: e.marginMin ?? null,
			declaredMarginMin: e.declaredMarginMin ?? null,
			canInvert: e.canInvert === true,
			measured: e.measured ?? null
		}))
		.sort(
			(a, b) =>
				Number(b.canInvert) - Number(a.canInvert) ||
				(a.declaredMarginMin ?? 0) - (b.declaredMarginMin ?? 0)
		);
}

/**
 * Mutex folding for the canvas. 56 pairwise exclusion edges are truthful data
 * and unreadable ink — 11 claimants of one lock alone are 55 pairs. The
 * canvas draws one connector per CLAIM (node → resource), which carries the
 * same information in N lines instead of N(N−1)/2. The pairwise edges remain
 * in the artifact and in the inspector; this is presentation, not data loss.
 */
export interface MutexSpoke {
	node: string;
	resource: string;
}

export function mutexSpokes(graph: AnatomyGraph): MutexSpoke[] {
	const spokes = new Set<string>();
	for (const e of graph.edges) {
		if (e.kind !== 'mutex' || !e.resource) continue;
		spokes.add(`${e.from} resource:${e.resource}`);
		spokes.add(`${e.to} resource:${e.resource}`);
	}
	return [...spokes].sort().map((s) => {
		const [node, resource] = s.split(' ');
		return { node, resource };
	});
}

/** Kind filter + connected-only, the two knobs the canvas offers. Edges are
 *  kept only when BOTH endpoints are visible — a dangling arrow is a claim
 *  about a node the screen is hiding. */
export function filterForCanvas(
	graph: AnatomyGraph,
	visibleKinds: ReadonlySet<NodeKind>,
	connectedOnly: boolean
): { nodes: GraphNode[]; edges: GraphEdge[]; spokes: MutexSpoke[] } {
	const kindVisible = (id: string) => {
		const n = graph.byId.get(id);
		return n !== undefined && visibleKinds.has(n.kind);
	};
	const edges = graph.edges.filter(
		(e) => e.kind !== 'mutex' && kindVisible(e.from) && kindVisible(e.to)
	);
	const spokes = mutexSpokes(graph).filter((s) => kindVisible(s.node) && kindVisible(s.resource));
	const touched = new Set<string>();
	for (const e of edges) {
		touched.add(e.from);
		touched.add(e.to);
	}
	for (const s of spokes) {
		touched.add(s.node);
		touched.add(s.resource);
	}
	const nodes = graph.nodes.filter(
		(n) => visibleKinds.has(n.kind) && (!connectedOnly || touched.has(n.id))
	);
	const nodeIds = new Set(nodes.map((n) => n.id));
	return {
		nodes,
		edges: edges.filter((e) => nodeIds.has(e.from) && nodeIds.has(e.to)),
		spokes: spokes.filter((s) => nodeIds.has(s.node) && nodeIds.has(s.resource))
	};
}

/**
 * The constitution join — which paragraphs govern a set of nodes. This IS
 * the highlight the operator asked for: `governed_by` edges are citations
 * measured out of the nodes' own manifest blocks (per-block attribution,
 * tools/anatomy-graph-gen.py derive_doctrine), so the answer is what the
 * code actually cites, never a curated opinion.
 */
export interface GoverningParagraph {
	id: string;
	doc: string;
	section: string;
	heading: string;
	/** Which of the queried nodes cite it, with the citing line. */
	citedBy: { node: string; via: string; citations: number }[];
}

export function governingParagraphs(
	graph: AnatomyGraph,
	nodeIds: readonly string[]
): GoverningParagraph[] {
	const want = new Set(nodeIds);
	const byTarget = new Map<string, GoverningParagraph>();
	for (const e of graph.edges) {
		if (e.kind !== 'governed_by' || !want.has(e.from)) continue;
		const node = graph.byId.get(e.to);
		if (!node) continue;
		let p = byTarget.get(e.to);
		if (!p) {
			p = {
				id: e.to,
				doc: node.source,
				section: String(node.facts.section ?? ''),
				heading: String(node.facts.heading ?? ''),
				citedBy: []
			};
			byTarget.set(e.to, p);
		}
		p.citedBy.push({ node: e.from, via: e.via ?? '', citations: e.citations ?? 1 });
	}
	return [...byTarget.values()].sort((a, b) => a.id.localeCompare(b.id));
}

/**
 * Join the static graph with the live Pulse snapshot: `pulse:` node ids are
 * wing.db `pulse_jobs` ids verbatim, so the join is `id.slice('pulse:'.length)`.
 * Returns only ids present in BOTH — a graph node with no live row is the
 * "declared, never registered" finding and is reported separately.
 */
export interface LiveJoin {
	states: Map<string, string>;
	/** Graph pulse nodes with no registered job upstream. */
	unregistered: string[];
	/** Graph pulse nodes whose registered job has never run. */
	neverRan: string[];
}

export function joinLive(
	graph: AnatomyGraph,
	jobs: { id: string; state: string; neverRan: boolean }[] | undefined
): LiveJoin {
	const states = new Map<string, string>();
	const unregistered: string[] = [];
	const neverRan: string[] = [];
	const byJob = new Map((jobs ?? []).map((j) => [j.id, j]));
	for (const n of graph.nodes) {
		if (n.kind !== 'pulse') continue;
		const job = byJob.get(n.id.slice('pulse:'.length));
		if (!job) {
			unregistered.push(n.id);
			continue;
		}
		states.set(n.id, job.state);
		if (job.neverRan) neverRan.push(n.id);
	}
	return { states, unregistered, neverRan };
}

/**
 * SPOTLIGHT — the seven nodes a widget-sized surface can honestly show.
 *
 * THE RULE, and it is rendered on screen beside the picture because a
 * seven-node sample of a 190-odd-node graph is a claim about which seven:
 *
 *   the nodes of highest NON-MUTEX degree, ties broken by id ascending.
 *
 * Non-mutex because the 56 mutex edges are ONE lock counted N(N−1)/2 times —
 * eleven claimants of the agent-run lock alone are 55 pairs, so ranking by raw
 * degree would return "the eleven things that share a lock" every time and
 * call it the busiest part of the estate. `mutexSpokes()` already folds them
 * for the canvas for the same reason.
 *
 * Ties broken by id so the same artifact always yields the same seven: a
 * widget that reshuffled on every converge would teach the operator that its
 * contents mean nothing.
 *
 * Returns the INDUCED subgraph — only edges with both endpoints among the
 * seven. That subgraph is not connected (measured 2026-08-07: 7 nodes, 7
 * edges, 2 components) and the caller must say so rather than drawing a whole.
 */
export interface Spotlight {
	nodes: GraphNode[];
	edges: GraphEdge[];
	/** The rule, in one line, for the surface to render verbatim. */
	rule: string;
	/** Weakly-connected components of the induced subgraph. */
	components: number;
	/** The degree used for the ranking, per selected node. */
	degree: Map<string, number>;
}

export function spotlight(graph: AnatomyGraph, n = 7): Spotlight {
	const degree = new Map<string, number>();
	const bump = (id: string) => degree.set(id, (degree.get(id) ?? 0) + 1);
	for (const e of graph.edges) {
		if (e.kind === 'mutex') continue;
		bump(e.from);
		bump(e.to);
	}
	const nodes = [...graph.nodes]
		.sort((a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0) || a.id.localeCompare(b.id))
		.slice(0, Math.max(0, n));
	const ids = new Set(nodes.map((x) => x.id));
	const edges = graph.edges.filter((e) => e.kind !== 'mutex' && ids.has(e.from) && ids.has(e.to));

	// Weak components over the induced subgraph — union-find, small enough that
	// clarity beats cleverness.
	const parent = new Map<string, string>(nodes.map((x) => [x.id, x.id]));
	const find = (a: string): string => {
		let r = a;
		while (parent.get(r) !== r) r = parent.get(r)!;
		return r;
	};
	for (const e of edges) parent.set(find(e.from), find(e.to));
	const components = nodes.length === 0 ? 0 : new Set(nodes.map((x) => find(x.id))).size;

	return {
		nodes,
		edges,
		rule: `${nodes.length} nodes of highest degree (mutex pairs excluded), ties by id`,
		components,
		degree: new Map(nodes.map((x) => [x.id, degree.get(x.id) ?? 0]))
	};
}
