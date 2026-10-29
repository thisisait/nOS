// The wire as the webview sees it: already decoded by the Rust bridge with
// nos_contract::wire::decode_to_shell, so every message here is checked.
// Spec: files/anatomy/contracts/thalamus-shell.yml.
import type { Act, Acted, Limb } from '$lib/limbs/types';
import type { Delta } from './delta';
import type { Catalogue } from './marks';

export type Value = null | boolean | number | string | Value[] | { [k: string]: Value };

export type Component =
	| {
			kind: 'table_results';
			props: {
				table: string;
				name: string;
				query: string;
				matched: number;
				total: number;
				columns: string[];
				rows: { __id: string; cells: Record<string, Value> }[];
				projected: boolean;
			};
	  }
	| {
			kind: 'row_diff_approval';
			props: {
				table: string;
				title: string;
				op: 'insert' | 'update' | 'insert_many' | 'delete';
				row_id?: string;
				cells: CellChange[];
				read_from?: string[];
				lines?: Lines;
				warning?: string;
			};
	  }
	| { kind: 'table_schema_approval'; props: TableSchemaProps }
	| { kind: 'column_add_approval'; props: ColumnAddProps }
	| {
			kind: 'inbox_list';
			props: {
				items: { id: string; title: string; source: string; created_at: string }[];
				refused: string[];
			};
	  }
	| {
			kind: 'approvals_list';
			props: {
				items: {
					kind: string;
					severity: string;
					age: string;
					what: string;
					where: string;
					note?: string;
				}[];
				unknown: string[];
			};
	  }
	| {
			kind: 'red_status';
			props: { red_count: number; reds: string[]; hold_count: number; holds: string[] };
	  }
	| { kind: 'markdown'; props: { text: string } }
	| { kind: 'table'; props: { title?: string; columns: string[]; rows: Value[][] } }
	| {
			kind: 'list';
			props: {
				title?: string;
				ordered: boolean;
				items: {
					text: string;
					detail?: string;
					tone?: 'ok' | 'info' | 'warn' | 'bad';
					delta?: Delta;
				}[];
			};
	  }
	| {
			kind: 'record';
			props: {
				title?: string;
				fields: { key: string; value: Value; delta?: Delta; was?: Value }[];
			};
	  }
	| {
			kind: 'chart';
			props: {
				title?: string;
				chart: 'bar' | 'stacked_bar' | 'line' | 'area' | 'scatter' | 'pie';
				x: 'category' | 'number' | 'time';
				series: { name: string; points: [string, number][] }[];
			};
	  }
	| { kind: 'tree'; props: { title?: string; nodes: TreeNode[] } }
	| {
			kind: 'timeline';
			props: {
				title?: string;
				items: {
					when: string;
					title: string;
					note?: string;
					hi?: boolean;
					until?: string;
					lane?: string;
				}[];
			};
	  }
	| {
			kind: 'graph';
			props: {
				title?: string;
				nodes: {
					id: string;
					label: string;
					note?: string;
					tone?: 'ok' | 'info' | 'warn' | 'bad';
				}[];
				edges: { from: string; to: string; label?: string; dashed?: boolean }[];
			};
	  }
	| { kind: 'sequence'; props: { title?: string; participants: string[]; steps: SequenceStep[] } }
	| { kind: 'knowledge_tree'; props: KnowledgeProps }
	| { kind: 'dendrogram'; props: DendrogramProps }
	| { kind: 'form'; props: FormProps }
	| { kind: 'choice'; props: ChoiceProps }
	| {
			kind: 'callout';
			props: { tone: 'ok' | 'info' | 'warn' | 'bad'; title: string; text: string };
	  }
	| {
			kind: 'steps';
			props: {
				title?: string;
				items: {
					title: string;
					status: 'pending' | 'active';
					detail?: string;
				}[];
			};
	  }
	| {
			kind: 'sources';
			props: {
				title?: string;
				items: { table: string; row: string; name?: string; note?: string }[];
			};
	  }
	| { kind: 'follow_up'; props: { prompts: string[] } }
	| { kind: 'dashboard'; props: DashboardProps }
	| { kind: 'kpi'; props: KpiProps }
	| {
			kind: 'action_approval';
			props: { app: string; action: string; params: Record<string, Value>; says: string };
	  };

/** The ontology around one node of our knowledge (renderers.rs KnowledgeTree, v10); `hidden`: what the cap left out. */
export type KnowledgeProps = {
	title?: string;
	focus: string;
	nodes: { id: string; name: string; parent?: string; child_count?: number; text?: string }[];
	hidden: number;
};

/** One agent run as a tree (renderers.rs Dendrogram, v11): serve-built from Wing, one root; `hidden`: what the cap left out. */
export type DendrogramProps = {
	title?: string;
	root: string;
	nodes: {
		id: string;
		parent?: string;
		kind: 'agent' | 'thread' | 'turn' | 'tool' | 'approval' | 'iteration';
		name: string;
		status: 'running' | 'ok' | 'bad' | 'waiting';
		started?: string;
		ended?: string;
		tokens?: number;
		note?: string;
	}[];
	hidden: number;
};

/** One number serve computed from a table (renderers.rs Kpi); never the model's. */
export type KpiProps = {
	title: string;
	value: number;
	unit?: string;
	delta?: number;
	delta_label?: string;
	source?: string;
};

/** A new private table Iris proposes (renderers.rs TableSchemaApproval): every column, under one approval. */
export type TableSchemaProps = {
	title: string;
	description?: string;
	visibility: 'private';
	columns: SchemaColumn[];
};
export type SchemaColumn = {
	key: string;
	label: string;
	kind: 'text' | 'number' | 'date' | 'select' | 'boolean' | 'rowRef';
	required: boolean;
	options?: string[];
	ref_table?: string;
	ref_title?: string;
	ref_display?: string;
};

/** New columns for a table the person can read (renderers.rs ColumnAddApproval); `existing` is shown, never changed. */
export type ColumnAddProps = {
	table: string;
	title: string;
	existing: { key: string; label: string; kind: string }[];
	columns: SchemaColumn[];
};

/** A tab Iris offers (renderers.rs Dashboard): nothing runs until the person places it. */
export type DashboardProps = {
	name: string;
	lens: Lens[];
	widgets: { title: string; spec: WidgetSpec }[];
	dropped: { title: string; why: string }[];
};
/** A tab-wide condition (renderers.rs Lens); an empty value is unset. */
export type CellChange = { key: string; old: Value; new: Value };
/** insert_many: line items written after the parent, each with ref_key = the parent's id (one approval). */
export type Lines = { table: string; title: string; ref_key: string; rows: CellChange[][] };
export type Lens = {
	column: string;
	op: 'eq' | 'neq' | 'lt' | 'gt' | 'contains';
	value: string;
	kind?: FormField['kind'];
	options?: string[];
};

/** A question Iris asks at a fork (renderers.rs Choice); `id` is the one serve minted. */
export type ChoiceProps = {
	id?: string;
	question: string;
	options: { label: string; note?: string }[];
	suggested: string[];
	multi: boolean;
};

/** A widget form serve built from the table's schema (renderers.rs Form); never the model's. */
export type FormProps = {
	form: string;
	table: string;
	title: string;
	fields: FormField[];
	omitted: { key: string; kind: string }[];
	prefill?: Record<string, string | number | boolean>;
};
export type FormField = {
	key: string;
	label: string;
	kind: 'text' | 'number' | 'date' | 'select' | 'bool';
	required: boolean;
	options?: string[];
	min?: number;
	max?: number;
	placeholder?: string;
	when?: When;
};
/** A field is drawn and sent only while another field's draft holds (eq) or does not hold (neq) `value`. */
export type When = { key: string; op: 'eq' | 'neq'; value: string };

/** A sequence step (renderers.rs Step), told apart by its fields. */
export type SequenceStep =
	| { from: string; to: string; text: string; dashed?: boolean }
	| { note: string; over: string[] }
	| { phase: string };

export type TreeNode = { label: string; note?: string; delta?: Delta; children?: TreeNode[] };

export type ToShell =
	| { t: 'session'; session: string; actor: string; model_uri: string }
	| { t: 'text'; session: string; text: string }
	| { t: 'render'; session: string; component: Component; pin?: WidgetSpec }
	| { t: 'approval_request'; session: string; approval: string; component: Component }
	| { t: 'refused'; reason: string; widget?: string }
	| { t: 'activity'; session: string; phase: Phase }
	| { t: 'widget'; session: string; widget: string; component: Component }
	| { t: 'form_result'; session: string; widget: string; form: string; row: string }
	| { t: 'table_changed'; session: string; table: string; row: string }
	| { t: 'working_for'; session: string; scope: Scope; name: string }
	| { t: 'model_options'; session: string; options: ModelOption[]; refused: string[] }
	| { t: 'said'; session: string; text: string }
	| { t: 'replay'; session: string; log: ToShell[]; open: string[] }
	| { t: 'workspace'; doc: { [k: string]: Value } | null }
	| { t: 'catalogue'; session: string; tables: Catalogue['tables'] }
	| ({ t: 'act'; session: string } & Act)
	| { t: 'model_state'; session: string; loaded: boolean }
	| ({ t: 'state' } & EstateState);

/** The estate's set-points and host organs (wire.rs EstateState, v13); null is UNKNOWN, never off. */
export type SetPoint = { on: boolean | null; since?: string; reason?: string; file: string };
export type EstateState = {
	halt: SetPoint;
	loops_paused: SetPoint;
	organs: { name: string; label: string; running: boolean | null }[];
	/** Each setting state/genome/settings.yml names (v15); a value null is UNKNOWN, the map null when the genome is. */
	settings: { [key: string]: Value } | null;
	/** Only on the answer to halt / lift_halt (v14) or setting (v15): whether Wing recorded the act. */
	act?: { recorded: boolean; why?: string };
};

/** One model the person may pick for the session (wire.rs ModelOption); `warning` below the recommended size. */
export type ModelOption = {
	backend: string;
	model: string;
	processor: string;
	transfers_outside_eu: boolean;
	warning?: string;
	current: boolean;
};

/** Whom the person works for (wire.rs Scope): no wall, personal data, or one client party. */
export type Scope = 'all' | 'personal' | { client: string };

/** What the thalamus is doing (wire.rs Phase); the eye shows it, the log does not. */
export type Phase = 'thinking' | { tool: { name: string } } | 'writing' | 'idle';

export const phaseName = (p: Phase): string => (typeof p === 'string' ? p : `tool:${p.tool.name}`);

export type ToThalamus =
	| { t: 'turn'; session: string | null; text: string }
	| {
			t: 'approval_decision';
			approval: string;
			decision: 'approve' | 'reject';
			note: string | null;
	  }
	| { t: 'control'; view: 'inbox' | 'approvals' | 'red_status' }
	| {
			t: 'widget';
			widget: string;
			spec: WidgetSpec;
			trigger: 'click' | 'restore' | 'table_changed';
	  }
	| {
			t: 'form_submit';
			form: string;
			widget: string;
			values: Record<string, string | number | boolean>;
	  }
	| { t: 'choice_reply'; session: string; choice: string; picked: string[] }
	| { t: 'working_for'; scope: Scope }
	| { t: 'model_options' }
	| { t: 'model_pick'; backend: string; model: string }
	| { t: 'resume'; workspace?: string }
	| { t: 'clear' }
	| { t: 'branch'; workspace: string }
	| { t: 'stop'; session: string }
	| { t: 'workspace_load' }
	| { t: 'state' }
	| { t: 'halt'; reason?: string }
	| { t: 'lift_halt' }
	| { t: 'setting'; key: string; value: Value }
	| { t: 'workspace_save'; doc: { [k: string]: unknown } }
	| { t: 'catalogue' }
	| { t: 'limbs'; limbs: Limb[] }
	| ({ t: 'acted' } & Acted);

/** What a widget re-runs, as the person and without the model (wire.rs WidgetSpec): exactly one key. */
export type WidgetSpec =
	| { rows: Record<string, Value> }
	| {
			chart: {
				query: { table: string; q?: string; where?: Value[] };
				chart: 'bar' | 'line' | 'pie';
				x: string;
				y?: string;
				op: 'count' | 'sum' | 'avg';
			};
	  }
	| {
			form: {
				table: string;
				columns?: string[];
				prefill?: Record<string, string | number | boolean>;
				when?: Record<string, When>;
			};
	  }
	| {
			kpi: {
				query: { table: string; q?: string; where?: Value[] };
				op: 'count' | 'sum' | 'avg';
				y?: string;
				unit?: string;
			};
	  }
	| { knowledge: { node: string } };

export type Link = { state: 'connected' | 'closed'; reason: string | null };

/** A table cell as text; null is an empty cell, never the word "null". */
export const cell = (v: Value | undefined): string =>
	v === null || v === undefined ? '' : typeof v === 'string' ? v : JSON.stringify(v);

/** A diff side: an empty cell must not look like an empty string (shell.rs `shown`). */
export const shown = (v: Value): string => (v === null ? '(empty)' : JSON.stringify(v));
