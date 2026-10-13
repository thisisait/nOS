// The wire as the webview sees it: already decoded by the Rust bridge with
// nos_contract::wire::decode_to_shell, so every message here is checked.
// Spec: files/anatomy/contracts/thalamus-shell.yml.

export type Value = null | boolean | number | string | Value[] | { [k: string]: Value };

export type Component =
	| { kind: 'table_results'; props: { table: string; name: string; query: string; matched: number; total: number; columns: string[]; rows: { __id: string; cells: Record<string, Value> }[]; projected: boolean } }
	| { kind: 'row_diff_approval'; props: { table: string; row_id: string; cells: { key: string; old: Value; new: Value }[] } }
	| { kind: 'inbox_list'; props: { items: { id: string; title: string; source: string; created_at: string }[]; refused: string[] } }
	| { kind: 'approvals_list'; props: { items: { kind: string; severity: string; age: string; what: string; where: string; note?: string }[]; unknown: string[] } }
	| { kind: 'red_status'; props: { red_count: number; reds: string[]; hold_count: number; holds: string[] } }
	| { kind: 'markdown'; props: { text: string } }
	| { kind: 'table'; props: { title?: string; columns: string[]; rows: Value[][] } }
	| { kind: 'list'; props: { title?: string; ordered: boolean; items: { text: string; detail?: string; tone?: 'ok' | 'info' | 'warn' | 'bad' }[] } }
	| { kind: 'record'; props: { title?: string; fields: { key: string; value: Value }[] } }
	| { kind: 'chart'; props: { title?: string; chart: 'bar' | 'stacked_bar' | 'line' | 'area' | 'scatter' | 'pie'; x: 'category' | 'number' | 'time'; series: { name: string; points: [string, number][] }[] } }
	| { kind: 'tree'; props: { title?: string; nodes: TreeNode[] } }
	| { kind: 'timeline'; props: { title?: string; items: { when: string; title: string; note?: string; hi?: boolean; until?: string; lane?: string }[] } }
	| { kind: 'graph'; props: { title?: string; nodes: { id: string; label: string; note?: string; tone?: 'ok' | 'info' | 'warn' | 'bad' }[]; edges: { from: string; to: string; label?: string; dashed?: boolean }[] } }
	| { kind: 'form'; props: FormProps };

/** A widget form serve built from the table's schema (renderers.rs Form); never the model's. */
export type FormProps = { form: string; table: string; title: string; fields: FormField[]; omitted: { key: string; kind: string }[] };
export type FormField = {
	key: string; label: string; kind: 'text' | 'number' | 'date' | 'select' | 'bool'; required: boolean;
	options?: string[]; min?: number; max?: number; placeholder?: string;
};

export type TreeNode = { label: string; note?: string; children?: TreeNode[] };

export type ToShell =
	| { t: 'session'; session: string; actor: string; model_uri: string }
	| { t: 'text'; session: string; text: string }
	| { t: 'render'; session: string; component: Component }
	| { t: 'approval_request'; session: string; approval: string; component: Component }
	| { t: 'refused'; reason: string; widget?: string }
	| { t: 'activity'; session: string; phase: Phase }
	| { t: 'widget'; session: string; widget: string; component: Component };

/** What the thalamus is doing (wire.rs Phase); the eye shows it, the log does not. */
export type Phase = 'thinking' | { tool: { name: string } } | 'writing' | 'idle';

export const phaseName = (p: Phase): string => (typeof p === 'string' ? p : `tool:${p.tool.name}`);

export type ToThalamus =
	| { t: 'turn'; session: string | null; text: string }
	| { t: 'approval_decision'; approval: string; decision: 'approve' | 'reject'; note: string | null }
	| { t: 'control'; view: 'inbox' | 'approvals' | 'red_status' }
	| { t: 'widget'; widget: string; spec: WidgetSpec; trigger: 'click' | 'restore' | 'table_changed' };

/** What a widget re-runs, as the person and without the model (wire.rs WidgetSpec): exactly one key. */
export type WidgetSpec =
	| { rows: Record<string, Value> }
	| { chart: { query: { table: string; q?: string; where?: Value[] }; chart: 'bar' | 'line' | 'pie'; x: string; y?: string; op: 'count' | 'sum' | 'avg' } }
	| { form: { table: string; columns?: string[] } };

export type Link = { state: 'connected' | 'closed'; reason: string | null };

/** A table cell as text; null is an empty cell, never the word "null". */
export const cell = (v: Value | undefined): string =>
	v === null || v === undefined ? '' : typeof v === 'string' ? v : JSON.stringify(v);

/** A diff side: an empty cell must not look like an empty string (shell.rs `shown`). */
export const shown = (v: Value): string => (v === null ? '(empty)' : JSON.stringify(v));
