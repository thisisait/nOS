/** The root CA panel's projection of Bone /api/v1/estate/root-ca (row
 *  nos-root-ca-fingerprint-second-channel). Fail closed: "same" only when both digests are
 *  well-formed and equal; anything else Bone sent is dropped, and a free-text reason is capped. */
const SHA = /^([0-9A-F]{2}:){31}[0-9A-F]{2}$/;

export type Side = { sha256: string } | { unknown: string };
export interface RootCaView {
	trusted: Side & { subject?: string; notAfter?: string };
	served: Side;
	agree: boolean;
}

const str = (v: unknown, n: number) => (typeof v === 'string' ? v.slice(0, n) : '');

function side(v: unknown): Side {
	const o = (v ?? {}) as Record<string, unknown>;
	if (typeof o.sha256 === 'string' && SHA.test(o.sha256)) return { sha256: o.sha256 };
	return { unknown: str(o.unknown, 200) || 'Bone did not say' };
}

export function projectRootCa(raw: unknown): RootCaView {
	const o = (raw ?? {}) as Record<string, unknown>;
	const t = (o.trusted ?? {}) as Record<string, unknown>;
	const trusted: RootCaView['trusted'] = side(t);
	if ('sha256' in trusted) {
		if (str(t.subject, 300)) trusted.subject = str(t.subject, 300);
		if (str(t.not_after, 40)) trusted.notAfter = str(t.not_after, 40);
	}
	const served = side(o.served);
	const agree =
		o.agree === true &&
		'sha256' in trusted &&
		'sha256' in served &&
		trusted.sha256 === served.sha256;
	return { trusted, served, agree };
}
