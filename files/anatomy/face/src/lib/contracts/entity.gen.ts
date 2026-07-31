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
