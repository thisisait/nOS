// GENERATED — do not edit. Source: state/genome/entity.schema.json (via tools/genome-codegen.py).
//
// Replaces the hand-mirrored contract between face and KEAP, which had already
// drifted before this file existed: face's ColumnKind carried 11 kinds to
// KEAP's 12, and every constraint was dropped on the way across. Nothing
// compared them, so a typo'd kind passed nOS CI and failed at KEAP's zod parse
// during the seeder run.

export type LegalBasis = 'consent' | 'contract' | 'legal_obligation' | 'vital_interests' | 'public_task' | 'legitimate_interests';
export const LEGAL_BASIS = ['consent', 'contract', 'legal_obligation', 'vital_interests', 'public_task', 'legitimate_interests'] as const;

export type AccessGate = 'none' | 'forward_auth' | 'oidc' | 'header_oidc';
export const ACCESS_GATES = ['none', 'forward_auth', 'oidc', 'header_oidc'] as const;

export type FaceSurface = 'window' | 'panel' | 'embed' | 'hidden';
export const FACE_SURFACES = ['window', 'panel', 'embed', 'hidden'] as const;

/** The adjective axes. A fourth one is a genome edit, not a fifth file. */
export const AXES = ['form', 'build', 'layer'] as const;

/** What an app IS on screen — one per app, always declared, never inferred. */
export type AppForm = 'view' | 'utility' | 'widget' | 'frame';
export const APP_FORMS = ['view', 'utility', 'widget', 'frame'] as const;

/** What an app COST to build. Independent of `form`; nothing derives either
 *  from the other. `docs/doctrine/face-app-tiers.md` owns the axis. */
export type AppBuild = 'F1' | 'F2' | 'F3' | 'F4' | 'H';
export const APP_BUILDS = ['F1', 'F2', 'F3', 'F4', 'H'] as const;

/** Where a service SITS. DERIVED, never declared. `null` — a service the
 *  estate refuses to place — is not in this list; it is not a fifth layer. */
export type ServiceLayer = 'L0' | 'L1' | 'L2' | 'L3';
export const SERVICE_LAYERS = ['L0', 'L1', 'L2', 'L3'] as const;

/** LLM providers that have an adapter. Adapter first, enum second — a member
 *  with no adapter is a URI the schema accepts and the Factory throws on. */
export type LlmProvider = 'anthropic' | 'claude' | 'openai' | 'openclaw';
export const LLM_PROVIDERS = ['anthropic', 'claude', 'openai', 'openclaw'] as const;

/** `<provider>-<the vendor's own model id>`. DERIVED from LLM_PROVIDERS. The
 *  tail keeps colons: every real ollama tag has one, and a spelling that cannot
 *  express the right value gets approximated into a wrong one — which is how
 *  nine agents came to name `qwen-coder-32b`, a model that does not exist. */
export const MODEL_URI_PATTERN = /^(anthropic|claude|openai|openclaw)-[A-Za-z0-9._:/-]{1,96}$/;

export const ANCHOR_PATTERN = /^[0-9]{2}(\.[0-9]{2}){0,2}$/;
export const LAYER_WITHHELD_MIN_LENGTH = 40;

/** The absence twin of ungatedRouteNeedsJustification: a withheld layer that
 *  does not say why reads as a default, and a default reads as calm. */
export function withheldLayerNeedsAReason(axes: {
  layer?: ServiceLayer | null;
  layer_withheld?: string;
}): boolean {
  if (!('layer' in axes) || axes.layer !== null) return false;
  return (axes.layer_withheld ?? '').trim().length < LAYER_WITHHELD_MIN_LENGTH;
}

export const IDENTITY_REQUIRED = ['name', 'version', 'description', 'kind'] as const;
export const COMPLIANCE_REQUIRED = ['purpose', 'legal_basis', 'data_categories', 'data_subjects', 'retention_days', 'processors'] as const;
export const ACCESS_REQUIRED = ['routed', 'gate'] as const;
export const ENTITY_REQUIRED = ['identity', 'compliance'] as const;

export const NAME_PATTERN = /^[a-z][a-z0-9-]{1,62}[a-z0-9]$/;
export const JUSTIFICATION_MIN_LENGTH = 40;
export const TIER_MIN = 1;
export const TIER_MAX = 4;

/** A routed entity with no gate is anonymously reachable — REM-144's shape. */
export function ungatedRouteNeedsJustification(access: {
  routed?: boolean;
  gate?: AccessGate;
  justification?: string;
}): boolean {
  if (!access.routed) return false;
  if (access.gate !== 'none') return false;
  return (access.justification ?? '').trim().length < JUSTIFICATION_MIN_LENGTH;
}
