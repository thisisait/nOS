// The wire as the webview sees it: already decoded by the Rust bridge with
// nos_contract::wire::decode_to_shell, so every message here is checked.
// Spec: files/anatomy/contracts/thalamus-shell.yml.
import type { Delta } from './delta';

export type Value = null | boolean | number | string | Value[] | { [k: string]: Value };

export type Component =
	| { kind: 'table_results'; props: { table: string; name: string; query: string; matched: number; total: number; columns: string[]; rows: { __id: string; cells: Record<string, Value> }[]; projected: boolean } }
	| { kind: 'row_diff_approval'; props: { table: string; title: string; op: 'insert' | 'update' | 'insert_many'; row_id?: string; cells: CellChange[]; read_from?: string[]; lines?: Lines } }
	| { kind: 'inbox_list'; props: { items: { id: string; title: string; source: string; created_at: string }[]; refused: string[] } }
	| { kind: 'approvals_list'; props: { items: { kind: string; severity: string; age: string; what: string; where: string; note?: string }[]; unknown: string[] } }
	| { kind: 'red_status'; props: { red_count: number; reds: string[]; hold_count: number; holds: string[] } }
	| { kind: 'markdown'; props: { text: string } }
	| { kind: 'table'; props: { title?: string; columns: string[]; rows: Value[][] } }
	| { kind: 'list'; props: { title?: string; ordered: boolean; items: { text: string; detail?: string; tone?: 'ok' | 'info' | 'warn' | 'bad'; delta?: Delta }[] } }
	| { kind: 'record'; props: { title?: string; fields: { key: string; value: Value; delta?: Delta; was?: Value }[] } }
	| { kind: 'chart'; props: { title?: string; chart: 'bar' | 'stacked_bar' | 'line' | 'area' | 'scatter' | 'pie'; x: 'category' | 'number' | 'time'; series: { name: string; points: [string, number][] }[] } }
	| { kind: 'tree'; props: { title?: string; nodes: TreeNode[] } }
	| { kind: 'timeline'; props: { title?: string; items: { when: string; title: string; note?: string; hi?: boolean; until?: string; lane?: string }[] } }
	| { kind: 'graph'; props: { title?: string; nodes: { id: string; label: string; note?: string; tone?: 'ok' | 'info' | 'warn' | 'bad' }[]; edges: { from: string; to: string; label?: string; dashed?: boolean }[] } }
	| { kind: 'sequence'; props: { title?: string; participants: string[]; steps: SequenceStep[] } }
	| { kind: 'form'; props: FormProps }
	| { kind: 'choice'; props: ChoiceProps }
	| { kind: 'dashboard'; props: DashboardProps };

/** A tab Iris offers (renderers.rs Dashboard): nothing runs until the person places it. */
export type DashboardProps = { name: string; lens: Lens[]; widgets: { title: string; spec: WidgetSpec }[]; dropped: { title: string; why: string }[] };
/** A placed dashboard as KEAP keeps it for the person (renderers.rs SavedDashboard): the offer under its tab id. */
export type SavedDashboard = { slug: string; name: string; lens: Lens[]; widgets: { title: string; spec: WidgetSpec }[] };
/** A tab-wide condition (renderers.rs Lens); an empty value is unset. */
export type CellChange = { key: string; old: Value; new: Value };
/** insert_many: line items written after the parent, each with ref_key = the parent's id (one approval). */
export type Lines = { table: string; title: string; ref_key: string; rows: CellChange[][] };
export type Lens = { column: string; op: 'eq' | 'neq' | 'lt' | 'gt' | 'contains'; value: string; kind?: FormField['kind']; options?: string[] };

/** A question Iris asks at a fork (renderers.rs Choice); `id` is the one serve minted. */
export type ChoiceProps = { id?: string; question: string; options: { label: string; note?: string }[]; suggested: string[]; multi: boolean };

/** A widget form serve built from the table's schema (renderers.rs Form); never the model's. */
export type FormProps = {
	form: string; table: string; title: string; fields: FormField[]; omitted: { key: string; kind: string }[];
	prefill?: Record<string, string | number | boolean>;
};
export type FormField = {
	key: string; label: string; kind: 'text' | 'number' | 'date' | 'select' | 'bool'; required: boolean;
	options?: string[]; min?: number; max?: number; placeholder?: string; when?: When;
};
/** A field is drawn and sent only while another field's draft holds (eq) or does not hold (neq) `value`. */
export type When = { key: string; op: 'eq' | 'neq'; value: string };

/** A sequence step (renderers.rs Step), told apart by its fields. */
export type SequenceStep = { from: string; to: string; text: string; dashed?: boolean } | { note: string; over: string[] } | { phase: string };

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
	| { t: 'dashboards'; session: string; dashboards: SavedDashboard[]; left_out: { title: string; why: string }[] }
	| { t: 'dashboard_saved'; session: string; slug: string; row: string };

/** What the thalamus is doing (wire.rs Phase); the eye shows it, the log does not. */
export type Phase = 'thinking' | { tool: { name: string } } | 'writing' | 'idle';

export const phaseName = (p: Phase): string => (typeof p === 'string' ? p : `tool:${p.tool.name}`);

export type ToThalamus =
	| { t: 'turn'; session: string | null; text: string }
	| { t: 'approval_decision'; approval: string; decision: 'approve' | 'reject'; note: string | null }
	| { t: 'control'; view: 'inbox' | 'approvals' | 'red_status' }
	| { t: 'widget'; widget: string; spec: WidgetSpec; trigger: 'click' | 'restore' | 'table_changed' }
	| { t: 'form_submit'; form: string; widget: string; values: Record<string, string | number | boolean> }
	| { t: 'choice_reply'; session: string; choice: string; picked: string[] }
	| { t: 'dashboard_save'; dashboard: SavedDashboard }
	| { t: 'dashboard_list' };

/** What a widget re-runs, as the person and without the model (wire.rs WidgetSpec): exactly one key. */
export type WidgetSpec =
	| { rows: Record<string, Value> }
	| { chart: { query: { table: string; q?: string; where?: Value[] }; chart: 'bar' | 'line' | 'pie'; x: string; y?: string; op: 'count' | 'sum' | 'avg' } }
	| { form: { table: string; columns?: string[]; prefill?: Record<string, string | number | boolean>; when?: Record<string, When> } };

export type Link = { state: 'connected' | 'closed'; reason: string | null };

/** A table cell as text; null is an empty cell, never the word "null". */
export const cell = (v: Value | undefined): string =>
	v === null || v === undefined ? '' : typeof v === 'string' ? v : JSON.stringify(v);

/** A diff side: an empty cell must not look like an empty string (shell.rs `shown`). */
export const shown = (v: Value): string => (v === null ? '(empty)' : JSON.stringify(v));
