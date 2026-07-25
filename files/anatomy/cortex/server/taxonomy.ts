/**
 * Seed taxonomy access for the backend.
 *
 * The 12-domain / 790-node tree lives in src/game/data/taxonomy.ts (the repo's
 * core asset) and is compiled into the server build via tsconfig.server.json.
 *
 * - generateTaxonomyOptions() is ported verbatim from the old apiServer.ts —
 *   it flattens the two top levels into <select> options for the Admin CMS.
 * - flattenTaxonomy() flattens the WHOLE tree (categories, subcategories at
 *   any depth, leaf items) for the agent surface: lookup by id, ancestors,
 *   children, and the FTS index.
 */
import { taxonomyData } from '../src/game/data/taxonomy';
import type { TaxonomyItem, TaxonomySubcategory } from '../src/game/types/taxonomy';

export interface TaxonomyOption {
  value: string;
  label: string;
  level: number;
}

export type TaxonomyZone = 'anchor' | 'votable' | 'free';

export interface FlatNode {
  id: string;
  name: string;
  /** Canonical (en) description — seed text or the curated K1 override.
   *  This is what FTS, embeddings and hybrid search read. */
  description?: string;
  /** Czech localization of the curated description (UI-only). */
  descriptionCs?: string;
  /** True when description comes from node_descriptions (K1 override). */
  descCurated?: boolean;
  kind: 'category' | 'subcategory' | 'item';
  parentId: string | null;
  /** Human-readable ancestry, e.g. "Natural Sciences > Physics > Kinematics" */
  path: string;
  requiredData?: string;
  questType?: string;
  childIds: string[];
  /** Track T governance zone (derived from depth; explicit on ext nodes). */
  zone: TaxonomyZone;
  /** True for dynamically grown nodes (taxonomy_nodes_ext), absent on the seed. */
  ext?: boolean;
}

/**
 * Track T governance zones by topological depth:
 *   0-1  anchor core  — hardcoded, changes only by release
 *   2-4  votable core — moderated extension proposals
 *   5+   free zone    — organic growth, light approval
 */
export function zoneOfLevel(level: number): TaxonomyZone {
  if (level <= 1) return 'anchor';
  if (level <= 4) return 'votable';
  return 'free';
}

export function nodeLevel(id: string): number {
  let level = 0;
  let cur = nodesById.get(id)?.parentId ?? null;
  while (cur) {
    level++;
    cur = nodesById.get(cur)?.parentId ?? null;
  }
  return level;
}

export function generateTaxonomyOptions(): TaxonomyOption[] {
  const options: TaxonomyOption[] = [];
  let categoryIndex = 1;

  Object.values(taxonomyData).forEach((category) => {
    const categoryId = String(categoryIndex).padStart(2, '0');
    options.push({ value: categoryId, label: `${categoryId} - ${category.name}`, level: 0 });

    let subcategoryIndex = 1;
    if (category.subcategories) {
      Object.values(category.subcategories).forEach((subcat) => {
        const subcatId = `${categoryId}.${String(subcategoryIndex).padStart(2, '0')}`;
        options.push({ value: subcatId, label: `${subcatId} - ${subcat.name}`, level: 1 });
        subcategoryIndex++;
      });
    }

    categoryIndex++;
  });

  return options;
}

// ── Full flatten (built once at module load; the dataset is static) ───────────

const nodesById = new Map<string, FlatNode>();

function addNode(node: FlatNode) {
  nodesById.set(node.id, node);
  if (node.parentId) {
    const parent = nodesById.get(node.parentId);
    if (parent) parent.childIds.push(node.id);
  }
}

function walkSubcategory(sub: TaxonomySubcategory, parentId: string, parentPath: string) {
  const path = `${parentPath} > ${sub.name}`;
  addNode({
    id: sub.id,
    name: sub.name,
    description: sub.description,
    kind: 'subcategory',
    parentId,
    path: parentPath,
    childIds: [],
    zone: 'votable',
  });
  for (const child of Object.values(sub.subcategories ?? {})) {
    walkSubcategory(child, sub.id, path);
  }
  for (const item of sub.items ?? []) {
    addNode({
      id: item.id,
      name: item.name,
      description: item.description,
      kind: 'item',
      parentId: sub.id,
      path,
      requiredData: (item as TaxonomyItem).requiredData,
      questType: (item as TaxonomyItem).questType,
      childIds: [],
      zone: 'votable',
    });
  }
}

for (const category of Object.values(taxonomyData)) {
  addNode({
    id: category.id,
    name: category.name,
    description: category.description,
    kind: 'category',
    parentId: null,
    path: '',
    childIds: [],
    zone: 'anchor',
  });
  for (const sub of Object.values(category.subcategories ?? {})) {
    walkSubcategory(sub, category.id, category.name);
  }
}

export function allNodes(): FlatNode[] {
  return [...nodesById.values()];
}

export function getNode(id: string): FlatNode | null {
  return nodesById.get(id) ?? null;
}

export function getAncestors(id: string): Array<{ id: string; name: string }> {
  const out: Array<{ id: string; name: string }> = [];
  let cur = nodesById.get(id)?.parentId ?? null;
  while (cur) {
    const n = nodesById.get(cur);
    if (!n) break;
    out.unshift({ id: n.id, name: n.name });
    cur = n.parentId;
  }
  return out;
}

// Zone finalize: depth is only known once the whole seed is in the map.
for (const n of nodesById.values()) {
  n.zone = zoneOfLevel(nodeLevel(n.id));
}

/** The immutable seed (static dataset only) — the U1 bake's input. */
export function staticNodes(): FlatNode[] {
  return [...nodesById.values()].filter((n) => !n.ext);
}

/**
 * Merge one approved dynamic node (taxonomy_nodes_ext) into the live tree.
 * Idempotent; called at startup for every stored row and immediately after
 * an approval materializes a node.
 */
/** A USER-DEFINED taxonomy root: one bare lowercase slug, e.g. `nos`.
 *
 *  Slugs cannot collide with the seed domains, which are two-digit numerals —
 *  the disjointness is structural, not a reserved range anyone has to remember.
 *
 *  A user root is always an EXT node appended to the layout, never baked into
 *  the seed ring: `bakeLayout` places roots at `angle = i / categories.length`,
 *  so admitting one to the static spine would change the divisor, move all
 *  twelve existing domains, and destroy spatial memory in a single release. */
export function isUserRootId(id: string): boolean {
  return /^[a-z][a-z0-9-]*$/.test(id);
}

/**
 * Merge one grown node into the live tree.
 *
 * A row with an EMPTY parentId is a user-defined ROOT (`parent_id` is NOT NULL
 * in the table, so '' is the sentinel). Roots are accepted only inside the
 * reserved range — an unrestricted parentless node would be indistinguishable
 * from a grown node whose parent failed to resolve, which is precisely the
 * silent-orphan case the parent check exists to catch.
 */
export function registerExtNode(row: {
  id: string;
  parentId: string;
  name: string;
  description: string;
  zone: string;
}): FlatNode | null {
  if (nodesById.has(row.id)) return nodesById.get(row.id)!;
  const isRoot = !row.parentId;
  if (isRoot && !isUserRootId(row.id)) return null;
  const parent = isRoot ? null : nodesById.get(row.parentId);
  if (!isRoot && !parent) return null;
  const node: FlatNode = {
    id: row.id,
    name: row.name,
    description: row.description,
    // A root is a category, like the seed domains it sits beside — `kind` drives
    // rendering weight, so labelling it 'item' would draw a domain as a leaf.
    kind: isRoot ? 'category' : 'item',
    parentId: isRoot ? null : row.parentId,
    path: isRoot ? '' : parent!.path ? `${parent!.path} > ${parent!.name}` : parent!.name,
    childIds: [],
    zone: row.zone as TaxonomyZone,
    ext: true,
  };
  nodesById.set(node.id, node);
  if (parent) parent.childIds.push(node.id);
  return node;
}

/**
 * Register EVERY stored grown node, as a fixpoint rather than one pass.
 *
 * listExtNodes orders by (created_at, ordinal), and ingest.mjs applies canonical
 * FILES in directory order with a monotonic created_at — so a slug subtree can
 * legitimately arrive children-first ('nos.infra.json' sorts before 'nos.json',
 * giving every child an EARLIER created_at than its root). One pass would drop
 * the children silently (parent not registered yet), and registration happens
 * only at boot, so the entire subtree would stay invisible until some later
 * restart happened to order differently. The layout append learned this lesson
 * first (ensureLayout's fixpoint); registration needs the same discipline.
 */
export function registerExtNodes(
  rows: Array<{ id: string; parentId: string; name: string; description: string; zone: string }>,
): { registered: number; dropped: string[] } {
  let registered = 0;
  const pending = [...rows];
  for (let pass = 0; pass < MAX_REGISTRATION_PASSES && pending.length; pass++) {
    const before = pending.length;
    for (let i = pending.length - 1; i >= 0; i--) {
      if (registerExtNode(pending[i])) {
        pending.splice(i, 1);
        registered++;
      }
    }
    if (pending.length === before) break; // no progress — the rest are unregisterable
  }
  const dropped = pending.map((r) => r.id);
  if (dropped.length) {
    console.warn(
      `[taxonomy] ${dropped.length} grown node(s) unregisterable (parent missing or a root outside the slug shape): ` +
        dropped.slice(0, 5).join(', '),
    );
  }
  return { registered, dropped };
}

// A taxonomy deeper than this is a bug, not a tree — the fixpoint must terminate.
const MAX_REGISTRATION_PASSES = 12;

export function taxonomyNodeCount(): number {
  return nodesById.size;
}

/**
 * Apply one curated description override (node_descriptions row) onto the
 * live tree. Idempotent; called at startup for every stored row and right
 * after a kind='desc' promotion approval. Mutating FlatNode.description is
 * the whole trick: FTS rebuild + the embeddings pending diff (content_hash
 * of name+path+description) + hybrid search all read this field.
 */
export function applyDescriptionOverride(row: {
  nodeId: string;
  descriptionEn: string;
  descriptionCs?: string;
}): boolean {
  const node = nodesById.get(row.nodeId);
  if (!node) return false;
  node.description = row.descriptionEn;
  node.descriptionCs = row.descriptionCs;
  node.descCurated = true;
  return true;
}
