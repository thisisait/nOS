// The selected marks of a chart, by id: a click or Enter toggles one.
export const toggle = (sel: readonly string[], id: string) =>
	sel.includes(id) ? sel.filter((s) => s !== id) : [...sel, id];

/** Dim the rest only while something is selected. */
export const dimmed = (sel: readonly string[], id: string) => sel.length > 0 && !sel.includes(id);
